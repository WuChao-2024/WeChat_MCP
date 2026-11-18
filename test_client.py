# -*- coding: utf-8 -*-
"""端到端自检：以 MCP 客户端身份拉起本项目的 server 并逐项验证。

用法：.venv\\Scripts\\python.exe test_client.py
协议级失败（握手/工具缺失）→ 退出码 1；微信未登录只提示不算失败。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
SERVER = ROOT / "wechat_reader_mcp" / "server.py"

EXPECTED = ["wechat_status", "wechat_sessions", "wechat_read", "wechat_contacts",
            "wechat_listen_add", "wechat_listen_remove", "wechat_listen_poll"]


def brief(text, n=400):
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[:n] + " ..."


async def main() -> int:
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=str(VENV_PY), args=[str(SERVER)], cwd=str(Path.home()))
    failures = []

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("[1] MCP 握手 (stdio) ............ OK")

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            missing = [t for t in EXPECTED if t not in names]
            if missing:
                failures.append(f"缺少工具: {missing}")
            has_send = "wechat_send" in names
            print(f"[2] 工具列表 ({len(names)} 个) ........ {'OK' if not missing else 'FAIL'}"
                  f"{'（含 wechat_send，allow_send 已开启）' if has_send else '（wechat_send 未注册=默认只读）'}")

            r = await session.call_tool("wechat_status", {})
            data = json.loads(r.content[0].text)
            if data.get("ok"):
                print(f"[3] 连接微信 .................... OK "
                      f"({data.get('client', {}).get('version')}, {data.get('me', {}).get('nickname')})")
            else:
                print(f"[3] 连接微信 .................... 跳过（{brief(data.get('error', ''), 120)}）")
                print("    → 打开微信桌面端并登录后重试；协议与工具已验证可用。")
                return 1 if failures else 0

            r = await session.call_tool("wechat_sessions", {})
            data = json.loads(r.content[0].text)
            print(f"[4] 会话列表 .................... OK（{data.get('count')} 个会话）"
                  if data.get("ok") else f"[4] 会话列表 .................... FAIL {brief(r.content[0].text, 120)}")
            if not data.get("ok"):
                failures.append("wechat_sessions 失败")

            r = await session.call_tool("wechat_read", {"chat": "filehelper", "limit": 3})
            data = json.loads(r.content[0].text)
            if data.get("ok"):
                print(f"[5] 读取 filehelper ............. OK（最近 {data.get('count')} 条，"
                      f"has_more_older={data.get('has_more_older')}）")
            else:
                print(f"[5] 读取 filehelper ............. 跳过（{brief(data.get('error', ''), 100)}）")

    if failures:
        print("\n自检未通过：", "; ".join(failures))
        return 1
    print("\n自检通过：MCP server 工作正常，AI 客户端新会话即可使用。")
    return 0


if __name__ == "__main__":
    if not VENV_PY.exists():
        print(f"未找到 venv：{VENV_PY}\n请先双击 install.bat 完成安装。")
        sys.exit(1)
    import anyio
    sys.exit(anyio.run(main))
