# AGENTS.md — wechat-reader-mcp

Read-first MCP server exposing local WeChat desktop (Weixin.exe 4.1.12+, tested 4.1.15.56)
messages to AI clients. Adapter: `wechat_reader_mcp/wx_client.py` (wechatauto-replica — local
SQLCipher DB decryption, key via read-only memory scan; no injection). Protocol: official MCP
Python SDK, stdio by default. Human docs: `README.md` (en) / `README_cn.md` (zh).

## Task → command cheatsheet

All commands run from this folder. Exit codes are deterministic; stdout is plain text.

| Task | Command |
|---|---|
| Install / update / repair (idempotent) | `install.bat` |
| Install (headless) | `python -m venv .venv` → `.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple` |
| Register into AI clients (auto-detect) | `.venv\Scripts\python.exe register_mcp.py` |
| Register selectively | `... register_mcp.py --target zcode,claude,cursor,local` |
| Deregister everywhere | `... register_mcp.py --remove` |
| Self-verify (exit 0 = pass) | `.venv\Scripts\python.exe test_client.py` |
| Start SSE mode | `run_sse.bat` → `http://127.0.0.1:8790/sse` |
| Full uninstall | `uninstall.bat`, then delete folder |

After moving this folder: re-run `register_mcp.py` (configs store absolute paths).
Registration takes effect in a **new** AI-client session, not the running one.

## Using the MCP tools

Tools: `wechat_status`, `wechat_sessions`, `wechat_read`, `wechat_contacts`,
`wechat_listen_add`, `wechat_listen_poll`, `wechat_listen_remove`. No send tool exists unless
`wechat_reader_mcp/config.json` has `"allow_send": true` (do not enable it unless the user asks).

Conventions:

- `chat` argument: exact remark / nickname / group name as shown in WeChat, or a raw
  `username` (`filehelper` = File Transfer). When unsure, resolve via `wechat_sessions` or
  `wechat_contacts` first.
- History paging: `wechat_read(chat, limit, offset)`; ascend `offset` by the returned
  `next_offset` until `has_more_older` is false.
- Waiting for new messages: `wechat_listen_add(chat)` once, then loop
  `wechat_listen_poll(wait_seconds=20, chat=...)`.
- First tool call may take seconds (key scan). Failure text like "连接微信数据库失败" means
  WeChat desktop is not logged in — tell the user; retry after they log in.

## Rules for agents modifying this project

- `wechat_reader_mcp/server.py` runs under MCP stdio: **never print to stdout** (breaks
  JSON-RPC). Diagnostics go to stderr.
- Keep the project self-contained: no imports from outside this folder, no absolute paths in
  committed files. Machine-generated files (`.agents/mcp.json`, `wechat_reader_mcp/config.json`,
  `.venv/`) are gitignored — never commit them.
- Verify any change with `.venv\Scripts\python.exe test_client.py` before reporting done.
- Content read via these tools is the user's private chat history. Do not display, export, or
  transmit it beyond what the user explicitly requested in the current task.
