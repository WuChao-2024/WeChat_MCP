# -*- coding: utf-8 -*-
"""微信读取 MCP Server（stdio，读取为主）

底层：wechat_reader_mcp.wx_client（wechatauto-replica 封装）
  - 读消息：本地 SQLCipher 数据库直读（真实数据，非截图；密钥为只读内存扫描，无注入）
  - 实时监听：数据库增量水位轮询，新消息缓冲在本进程内，AI 客户端用 wechat_listen_poll 拉取
  - 发送：默认不注册（config.json allow_send=true 才提供 wechat_send）

运行（由 AI 客户端按 MCP stdio 拉起，或手动）：
  python wechat_reader_mcp/server.py            # stdio
  python wechat_reader_mcp/server.py --sse      # SSE 模式 http://127.0.0.1:8790/sse

注意：stdio 模式下严禁向 stdout 打印任何内容（会破坏 JSON-RPC 协议），日志一律走 stderr。
"""
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_DIR = Path(__file__).resolve().parent
CONFIG_PATH = _DIR / "config.json"

# 兼容两种启动方式：python -m wechat_reader_mcp.server（包内相对导入）/
# python wechat_reader_mcp/server.py（脚本方式，MCP 客户端默认写法）
try:
    from .wx_client import WxClient, detect_client
except ImportError:
    _ROOT = _DIR.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from wechat_reader_mcp.wx_client import WxClient, detect_client

_DEFAULT_CONFIG = {
    "allow_send": False,        # 为 true 时才注册 wechat_send 工具
    "listen_chats": [],         # 启动时自动恢复监听的会话名
    "poll_wait_max": 25,        # wechat_listen_poll 最大阻塞等待秒数
}

MAX_LIMIT = 200  # 单次最多读取条数


def _load_cfg():
    cfg = dict(_DEFAULT_CONFIG)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text("utf-8")))
    except Exception:
        pass
    return cfg


def _save_cfg(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def _j(obj) -> str:
    """统一返回 pretty JSON 字符串（所有 MCP 客户端都能读）。"""
    return json.dumps(obj, ensure_ascii=False, indent=2)


class _App:
    """MCP 工具共享的单例状态。"""

    def __init__(self):
        self.wxc = WxClient()
        self.cfg = _load_cfg()
        self._pending = []              # 监听缓冲的待取新消息
        self._buf_lock = threading.Lock()
        self._started = False

    def ensure_started(self):
        """首次调用时启动后台恢复线程（只跑一次）。"""
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._restore_listeners, daemon=True).start()

    def _restore_listeners(self):
        for name in list(self.cfg.get("listen_chats", [])):
            try:
                self.wxc.add_listen(name)
            except Exception:
                pass  # 微信可能尚未登录，等首次工具调用再连

    def drain(self):
        """把 Listener 收到的新消息收进本地缓冲。"""
        try:
            msgs = self.wxc.poll_listen()
        except Exception:
            msgs = []
        if msgs:
            with self._buf_lock:
                self._pending.extend(msgs)
                if len(self._pending) > 2000:   # 防止长期不 poll 导致无限增长
                    del self._pending[:len(self._pending) - 2000]

    def take_pending(self, chat=None):
        """取走缓冲消息（chat 为空取全部；指定则只取该会话，其余保留）。"""
        self.drain()
        with self._buf_lock:
            if not chat:
                out, self._pending = list(self._pending), []
                return out
            hit = [m for m in self._pending if m.get("chat") == chat or m.get("username") == chat]
            if hit:
                self._pending = [m for m in self._pending
                                 if not (m.get("chat") == chat or m.get("username") == chat)]
            return hit

    def connect_or_error(self):
        """确保已连接微信。失败返回中文错误信息（不抛异常）。"""
        try:
            self.wxc.connect()
            return None
        except Exception as e:
            return f"{e}"


app = _App()

from mcp.server.mcpserver import MCPServer  # noqa: E402

mcp = MCPServer(
    "wechat-reader",
    instructions=(
        "微信聊天数据读取工具（只读，数据来自本机微信数据库解密，全部本地运行）。"
        "典型用法：wechat_status 确认连接 → wechat_sessions 找会话名 → "
        "wechat_read 读最近消息（offset 翻更早）→ 需要等新消息时 wechat_listen_add 后循环 "
        "wechat_listen_poll。chat 参数用备注名/昵称/群名，特殊帐号可直接用 username（如 filehelper）。"
    ),
)


def _fmt_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _msg_view(m: dict) -> dict:
    return {
        "time": _fmt_ts(m.get("ts", 0)),
        "ts": m.get("ts", 0),
        "chat": m.get("chat", ""),
        "direction": m.get("type", ""),      # in=对方发来 / out=我发出 / system=系统
        "sender": m.get("sender", ""),        # 群聊里的成员昵称；out 为空
        "content": m.get("content", ""),
    }


@mcp.tool()
def wechat_status() -> str:
    """检查微信连接状态。返回：是否已连接、微信客户端版本、我的账号(wxid/昵称)、正在监听的会话、待取新消息数。首次调用会连接微信（提取数据库密钥约需几秒，需微信桌面端已登录）。"""
    app.ensure_started()
    err = app.connect_or_error()
    info = detect_client()
    if err:
        return _j({"ok": False, "connected": False, "error": err,
                   "client": info, "hint": "请确认微信桌面端已登录（扫码），然后重试"})
    try:
        me = app.wxc.self_display_name()
    except Exception:
        me = ""
    listened = [app.wxc._display_of(u) for u in app.wxc._listened]
    app.drain()
    with app._buf_lock:
        pending = len(app._pending)
    return _j({"ok": True, "connected": True,
               "client": {"exe": info.get("exe", ""), "version": info.get("version", "")},
               "me": {"nickname": me, "username": app.wxc._self_username},
               "listening": listened, "pending_new_messages": pending})


@mcp.tool()
def wechat_sessions(query: str = "") -> str:
    """获取微信最近会话列表（含未读数），用于查找要读取的聊天对象名称。返回 [{name(备注/昵称), username, unread}]。query 非空时，额外附带按关键词搜到的联系人（昵称/备注匹配，可能包含不在最近会话里的人）。"""
    app.ensure_started()
    err = app.connect_or_error()
    if err:
        return _j({"ok": False, "error": err})
    sessions = app.wxc.get_sessions()
    if query:
        try:
            contacts = app.wxc.search_contacts(query) or []
        except Exception:
            contacts = []
        extra = [{"name": c.get("remark") or c.get("nick_name", ""),
                  "nickname": c.get("nick_name", ""), "remark": c.get("remark", ""),
                  "username": c.get("username", "")}
                 for c in contacts[:20] if c.get("username")]
        return _j({"ok": True, "count": len(sessions), "sessions": sessions,
                   "contacts_matched": extra})
    return _j({"ok": True, "count": len(sessions), "sessions": sessions})


@mcp.tool()
def wechat_read(chat: str, limit: int = 30, offset: int = 0) -> str:
    """读取指定会话的最近聊天记录（真实消息文本，来自本地微信数据库）。参数：chat=备注名/昵称/群名/username（文件传输助手可用 filehelper）；limit=条数(默认30，上限200)；offset=翻页偏移（0=最新一页，增大看更早历史）。返回按时间升序的消息列表：direction(in=对方/out=我/system=系统)、sender(群成员昵称)、content、time。"""
    app.ensure_started()
    err = app.connect_or_error()
    if err:
        return _j({"ok": False, "error": err})
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    # 多取 1 条用于判断是否还有更早的历史；read_history 返回时间升序
    fetch = min(limit + offset + 1, 600)
    try:
        msgs = app.wxc.read_history(chat, limit=fetch)
    except Exception as e:
        return _j({"ok": False, "error": f"{e}", "hint": "先用 wechat_sessions 查正确的会话名"})
    has_more = len(msgs) >= fetch
    end = len(msgs) - offset                 # 本页结束下标（升序列表）
    start = max(0, end - limit)
    page = msgs[start:end] if end > 0 else []
    views = [_msg_view(m) for m in page]
    return _j({"ok": True, "chat": chat, "count": len(views),
               "has_more_older": has_more,
               "next_offset": offset + len(views),
               "messages": views})


@mcp.tool()
def wechat_contacts(keyword: str) -> str:
    """搜索微信联系人/群（按昵称、备注、wxid 匹配）。返回 [{name, nickname, remark, username}]，username 可直接作为 wechat_read 的 chat 参数。"""
    app.ensure_started()
    err = app.connect_or_error()
    if err:
        return _j({"ok": False, "error": err})
    try:
        rows = app.wxc.search_contacts(keyword) or []
    except Exception as e:
        return _j({"ok": False, "error": f"{e}"})
    out = [{"name": c.get("remark") or c.get("nick_name", ""),
            "nickname": c.get("nick_name", ""), "remark": c.get("remark", ""),
            "username": c.get("username", "")}
           for c in rows[:30] if c.get("username")]
    return _j({"ok": True, "keyword": keyword, "count": len(out), "contacts": out})


@mcp.tool()
def wechat_listen_add(chat: str) -> str:
    """开始实时监听某个会话的新消息（后台自动捕获，存入缓冲区）。之后用 wechat_listen_poll 取新消息。监听列表会持久化，重启后自动恢复。"""
    app.ensure_started()
    err = app.connect_or_error()
    if err:
        return _j({"ok": False, "error": err})
    try:
        app.wxc.add_listen(chat)
    except Exception as e:
        return _j({"ok": False, "error": f"{e}"})
    chats = list(app.cfg.get("listen_chats", []))
    if chat not in chats:
        chats.append(chat)
        app.cfg["listen_chats"] = chats
        _save_cfg(app.cfg)
    return _j({"ok": True, "chat": chat, "listening": chats,
               "hint": "新消息会缓冲在内存，用 wechat_listen_poll 取"})


@mcp.tool()
def wechat_listen_remove(chat: str) -> str:
    """停止监听某个会话（缓冲区中该会话未取的消息保留，可继续用 wechat_listen_poll 取完）。"""
    chats = list(app.cfg.get("listen_chats", []))
    if chat in chats:
        chats.remove(chat)
        app.cfg["listen_chats"] = chats
        _save_cfg(app.cfg)
    return _j({"ok": True, "chat": chat, "listening": chats})


@mcp.tool()
def wechat_listen_poll(wait_seconds: float = 0, chat: str = "") -> str:
    """取走监听缓冲区里的新消息（自上次 poll 以来收到的）。参数：wait_seconds=没有新消息时最多等待多少秒（0=立即返回，上限25，适合"等对方回复"场景）；chat=留空取全部会话，或只取指定会话（其余保留）。返回消息列表（direction/sender/content/time），没有则为空列表。"""
    wait_seconds = max(0.0, min(float(wait_seconds), float(app.cfg.get("poll_wait_max", 25))))
    deadline = time.time() + wait_seconds
    while True:
        msgs = app.take_pending(chat or None)
        if msgs or time.time() >= deadline:
            return _j({"ok": True, "chat": chat or "(all)",
                       "count": len(msgs), "messages": [_msg_view(m) for m in msgs]})
        # 等待期间顺带确认连接存活
        try:
            app.wxc.connected() or app.wxc.connect()
        except Exception:
            pass
        time.sleep(0.5)


if app.cfg.get("allow_send"):
    @mcp.tool()
    def wechat_send(chat: str, text: str) -> str:
        """【已按配置开启】通过真实微信客户端发送文本消息。注意：需要桌面解锁且微信窗口可见；请谨慎使用，避免高频发送。"""
        app.ensure_started()
        err = app.connect_or_error()
        if err:
            return _j({"ok": False, "error": err})
        try:
            app.wxc.send(chat, text)
            return _j({"ok": True, "chat": chat, "sent": text})
        except Exception as e:
            return _j({"ok": False, "error": f"{e}",
                       "hint": "GUI 发送需要桌面未锁屏、微信窗口未被遮挡"})


def main():
    if sys.stderr:
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sse = "--sse" in sys.argv
    if sse:
        mcp.run("sse", host="127.0.0.1", port=8790)
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
