# -*- coding: utf-8 -*-
"""把 wechat-reader MCP Server 注册进各 AI 客户端（一键接入）。

用法：
  python register_mcp.py            # 自动注册：检测到已安装的客户端全部写入 + 本项目 .agents/mcp.json
  python register_mcp.py --remove   # 从所有位置移除注册
  python register_mcp.py --target zcode,claude   # 只写指定目标（zcode/claude/cursor/local）
  python register_mcp.py --name wechat-reader    # 自定义服务器名

写入位置（均为标准 MCP stdio 配置，绝对路径在运行时解析——移动项目目录后重跑本脚本即可）：
  ZCode          ~/.zcode/cli/config.json            → mcp.servers
  Claude Desktop %APPDATA%\\Claude\\claude_desktop_config.json → mcpServers
  Cursor         ~/.cursor/mcp.json                  → mcpServers
  通用/本项目     <项目>/.agents/mcp.json             → mcpServers（AI 打开本项目文件夹即自动连接）
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
SERVER = ROOT / "wechat_reader_mcp" / "server.py"

EXPECTED_TOOLS = ["wechat_status", "wechat_sessions", "wechat_read", "wechat_contacts",
                  "wechat_listen_add", "wechat_listen_remove", "wechat_listen_poll"]


def _targets():
    """返回 {key: (配置文件路径, 顶层键, 是否嵌套 mcp.servers)}"""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    return {
        "zcode": (home / ".zcode" / "cli" / "config.json", "mcp.servers", True),
        "claude": (appdata / "Claude" / "claude_desktop_config.json", "mcpServers", False),
        "cursor": (home / ".cursor" / "mcp.json", "mcpServers", False),
        "local": (ROOT / ".agents" / "mcp.json", "mcpServers", False),
    }


def _installed(key: str, path: Path) -> bool:
    """local 永远可写；其他目标要求客户端目录存在（避免给没装的客户端造配置）。"""
    if key == "local":
        return True
    return path.parent.exists()


def _load(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)
        print(f"[warn] {path.name} 不是合法 JSON，已备份到 {bak.name} 后重建")
        return {}


def _save(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _entry():
    return {"command": str(VENV_PY), "args": [str(SERVER)]}


def _get_store(data: dict, top: str, nested: bool):
    if nested:
        mcp = data.setdefault("mcp", {})
        return mcp.setdefault("servers", {})
    return data.setdefault(top, {})


def register(keys, name):
    if not VENV_PY.exists():
        print(f"[error] 未找到 {VENV_PY}\n请先运行 install.bat（或手动创建 venv 并安装依赖）。")
        sys.exit(1)
    t = _targets()
    for key in keys:
        path, top, nested = t[key]
        if not _installed(key, path):
            print(f"[skip] {key:8s} 未检测到该客户端（{path.parent} 不存在）")
            continue
        data = _load(path)
        store = _get_store(data, top, nested)
        store[name] = _entry()
        _save(path, data)
        print(f"[ok]   {key:8s} 已注册 → {path}")


def remove(keys, name):
    t = _targets()
    for key in keys:
        path, top, nested = t[key]
        if not path.exists():
            continue
        data = _load(path)
        store = _get_store(data, top, nested)
        if name in store:
            del store[name]
            _save(path, data)
            print(f"[ok]   {key:8s} 已移除 → {path}")


def main():
    ap = argparse.ArgumentParser(description="注册/移除 wechat-reader MCP")
    ap.add_argument("--remove", action="store_true", help="移除而不是注册")
    ap.add_argument("--target", default="", help="逗号分隔：zcode,claude,cursor,local")
    ap.add_argument("--name", default="wechat-reader", help="MCP 服务器名（默认 wechat-reader）")
    args = ap.parse_args()

    all_keys = list(_targets().keys())
    keys = [k.strip() for k in args.target.split(",") if k.strip()] or all_keys

    print(f"项目目录：{ROOT}")
    print(f"服务器  ：{args.name}  ({SERVER.name})\n")
    if args.remove:
        remove(keys, args.name)
        return
    register(keys, args.name)
    print("\n完成。重启 AI 客户端 / 新开会话后生效。")
    print("新会话里 AI 可直接调用：", "、".join(EXPECTED_TOOLS))


if __name__ == "__main__":
    main()
