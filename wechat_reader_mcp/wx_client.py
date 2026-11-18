# -*- coding: utf-8 -*-
"""微信接入层（基于 wechatauto-replica，适配微信 4.1.12+ 硬渲染客户端）。

- 读消息：本地 SQLCipher 数据库直读（真实数据，非截图/OCR；只读内存扫描取密钥，无注入）
- 实时监听：wechatauto.db.Listener（数据库增量水位轮询，回调推入内部队列）
- 发送：wechatauto.guia.quick_send（UIA 热激活 + 坐标/OCR 兜底驱动真实客户端）

对外消息统一归一化为: {chat, type(in/out/system), sender, content, ts}
"""
import ctypes
import os
import struct
import threading
import time
from collections import deque

# 常见安装路径（按优先级）；4.x 客户端叫 Weixin.exe，3.9.x 叫 WeChat.exe
_CLIENT_CANDIDATES = [
    (r"C:\Program Files\Tencent\Weixin\Weixin.exe", "4.x"),
    (r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe", "4.x"),
    (r"C:\Program Files\Tencent\WeChat\WeChat.exe", "3.9.x"),
    (r"C:\Program Files (x86)\Tencent\WeChat\WeChat.exe", "3.9.x"),
]

# wechatauto 的友好类型 → 展示占位
_PLACEHOLDER_TYPES = {"图片", "语音", "视频", "动画表情", "位置",
                      "文件/链接/卡片", "音视频通话", "红包", "动画表情"}


def _file_version(path):
    """用 Win32 Version API 读 exe 的 ProductVersion。失败返回空串。"""
    try:
        size = ctypes.windll.version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        data = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(path, 0, size, data):
            return ""

        def query(key):
            buf = ctypes.c_wchar_p()
            blen = ctypes.c_uint()
            ok = ctypes.windll.version.VerQueryValueW(
                data, key, ctypes.byref(buf), ctypes.byref(blen))
            return buf.value if ok and buf.value else ""

        trans = query("\\VarFileInfo\\Translation")
        if trans:
            raw = trans.encode("utf-16-le", "replace")[:4]
            if len(raw) == 4:
                lang, cp = struct.unpack("<HH", raw)
                for key in (f"\\StringFileInfo\\{lang:04x}{cp:04x}\\ProductVersion",
                            f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileVersion"):
                    v = query(key)
                    if v:
                        return v
        for cp in ("080404b0", "040904b0"):
            v = query(f"\\StringFileInfo\\{cp}\\ProductVersion")
            if v:
                return v
    except Exception:
        pass
    return ""


def detect_client():
    """检测已安装的微信桌面客户端。返回 {'exe','version','gen'}。"""
    for path, gen in _CLIENT_CANDIDATES:
        if os.path.exists(path):
            return {"exe": path, "version": _file_version(path), "gen": gen}
    return {"exe": "", "version": "", "gen": ""}


class WxClient:
    """统一微信操作入口。线程安全（监听回调/服务线程共用）。"""

    def __init__(self):
        self._db = None
        self._listener = None
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._queue = deque()          # 归一化消息队列（Listener 回调 → poll_listen 消费）
        self._by_name = {}             # 显示名 -> username
        self._by_user = {}             # username -> 显示名
        self._listened = []            # 已监听的 username（重连后恢复）
        self._self_username = ""
        self.client_info = detect_client()

    # ---------------- 连接 ----------------

    def connected(self):
        return self._db is not None

    def connect(self):
        """连接微信（要求桌面端已登录：密钥在进程内存中）。失败抛 RuntimeError。"""
        with self._lock:
            if self._db is not None:
                return True
            try:
                from wechatauto import WeChatDB
                from wechatauto.db import Listener
            except ImportError as e:
                raise RuntimeError(f"未安装 wechatauto-replica（{e}）: pip install wechatauto-replica")
            try:
                self._db = WeChatDB()
                info = self._db.get_self_info() or {}
                self._self_username = info.get("username", "")
            except Exception as e:
                self._db = None
                raise RuntimeError(f"连接微信数据库失败：{e}。请确认微信桌面端已登录后重试。")
            try:
                self._listener = Listener(self._db, interval=1.0)
                self._listener.start()   # 先启动；add_listener 支持动态添加
            except Exception as e:
                raise RuntimeError(f"启动消息监听失败: {e}")
            # 重连后恢复之前的监听
            for username in list(self._listened):
                try:
                    self._listener.add_listener(username, self._on_message)
                except Exception:
                    pass
            return True

    def self_display_name(self):
        """自己的显示名（连接后可用）。"""
        if self._self_username:
            return self._display_of(self._self_username)
        return ""

    def reset(self):
        """丢弃当前连接（出错后可自动重连重建）。"""
        with self._lock:
            try:
                if self._listener is not None:
                    self._listener.stop()
            except Exception:
                pass
            self._listener = None
            self._db = None

    # ---------------- 名称解析 ----------------

    def _display_of(self, username):
        """username -> 显示名（备注优先于昵称，尽力而为）。"""
        if username in self._by_user:
            return self._by_user[username]
        name = username
        try:
            nick = (self._db.get_nickname(username) or "").strip()
            if nick:
                name = nick
        except Exception:
            pass
        self._by_user[username] = name
        self._by_name.setdefault(name, username)
        return name

    def _resolve(self, name):
        """显示名 -> username。找不到抛 RuntimeError。"""
        name = name.strip()
        if not name:
            raise RuntimeError("会话名为空")
        if name in self._by_name:
            return self._by_name[name]
        # 1) 会话列表精确匹配（备注或昵称）
        try:
            for s in self._db.get_sessions(limit=500):
                if s.get("username") == name:
                    self._bind(name, s["username"])
                    return s["username"]
                disp = self._display_of(s.get("username", ""))
                if disp == name:
                    self._bind(name, s["username"])
                    return s["username"]
        except Exception:
            pass
        # 2) 联系人搜索精确匹配
        try:
            for c in self._db.search_contact(name):
                if (c.get("nick_name") == name or c.get("remark") == name) \
                        and c.get("username"):
                    self._bind(name, c["username"])
                    return c["username"]
        except Exception:
            pass
        # 3) 群名解析
        try:
            gid = self._db.group_name_to_id(name)
            if gid:
                self._bind(name, gid)
                return gid
        except Exception:
            pass
        raise RuntimeError(
            f"未找到会话「{name}」。请确认名称（备注/昵称）与微信一致；"
            f"特殊帐号可用 filehelper（文件传输助手）。")

    def _bind(self, name, username):
        self._by_name[name] = username
        self._by_user[username] = name

    # ---------------- 会话列表 ----------------

    def get_sessions(self):
        """当前会话列表 [{name(显示名), username, unread}]（尽力而为）。"""
        with self._lock:
            if self._db is None:
                return []
            try:
                sessions = self._db.get_sessions(limit=100)
            except Exception:
                return []
        out = []
        for s in sessions:
            username = s.get("username", "")
            if not username or username.startswith("@placeholder"):
                continue
            out.append({"name": self._display_of(username),
                        "username": username,
                        "unread": s.get("unread", 0)})
        return out

    def search_contacts(self, keyword):
        """联系人搜索（显示名 + username + 备注），返回原始 dict 列表。"""
        with self._lock:
            if self._db is None:
                return []
            try:
                return self._db.search_contact(keyword) or []
            except Exception:
                return []

    # ---------------- 监听 ----------------

    def add_listen(self, name):
        """添加监听会话（显示名）。"""
        with self._lock:
            self.connect()
            username = self._resolve(name)
            self._listener.add_listener(username, self._on_message)
            if username not in self._listened:
                self._listened.append(username)
            self._bind(name, username)

    def _on_message(self, msg, _listener):
        """Listener 回调（wechatauto 工作线程）→ 归一化入队。"""
        try:
            username = msg.get("username", "")
            norm = self._normalize(username, msg)
            if norm:
                self._queue.append(norm)
        except Exception:
            pass

    def poll_listen(self):
        """取出并清空当前积压的新消息。"""
        with self._lock:
            msgs = list(self._queue)
            self._queue.clear()
        return msgs

    # ---------------- 历史消息 ----------------

    def read_history(self, name, limit=50):
        """读取指定会话最近 limit 条消息（时间升序返回）。"""
        with self._lock:
            self.connect()
            username = self._resolve(name)
            rows = self._db.get_messages(username, limit=int(limit)) or []
        rows = list(reversed(rows))          # get_messages 返回降序（新→旧）
        out = [self._normalize(username, r) for r in rows]
        return [m for m in out if m]

    # ---------------- 发送 ----------------

    def send(self, name, text):
        """通过真实客户端发送文本。成功返回 True，失败抛 RuntimeError。"""
        with self._lock:
            self.connect()
            username = self._resolve(name)
        from wechatauto.guia import quick_send
        with self._send_lock:                # GUI 操作串行化
            resp = quick_send(text, who=username, verify=True)
        if not getattr(resp, "is_success", False):
            raise RuntimeError(f"发送失败: {resp}")
        return True

    # ---------------- 归一化 ----------------

    def _normalize(self, username, m):
        """DB 消息行 → {chat, type(in/out/system), sender, content, ts}"""
        mtype = str(m.get("type", "") or "")
        content = str(m.get("content", "") or "").strip()
        sender_username = m.get("sender_username", "") or ""
        chat = self._display_of(username)

        if mtype == "系统消息":
            nt, content = "system", (content or "系统消息")
        elif sender_username and sender_username == self._self_username:
            nt = "out"
        else:
            nt = "in"

        if mtype in _PLACEHOLDER_TYPES or not content:
            content = f"[{mtype}]" if mtype else "[未知消息]"

        # 发送者显示名：群聊取成员昵称；单聊对方即会话名
        sender = ""
        if nt == "in":
            if sender_username and username.endswith("@chatroom"):
                sender = self._display_of(sender_username)
            elif not username.endswith("@chatroom"):
                sender = chat
        return {"chat": chat, "type": nt, "sender": sender,
                "content": content, "ts": float(m.get("create_time", 0) or time.time())}
