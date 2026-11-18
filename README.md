# wechat-reader-mcp

A self-contained, read-first **MCP (Model Context Protocol) server** that exposes your local
WeChat desktop messages to any MCP-capable AI client (ZCode, Claude Desktop, Cursor,
Cherry Studio, ...). One click to install, one command to register — the AI does the rest.

**中文文档：[README_cn.md](README_cn.md)**

- **Real data, not screenshots** — messages are read by decrypting the local WeChat database
  (SQLCipher). The key is obtained by a *read-only* memory scan of the running WeChat process:
  no DLL injection, no process modification, no network-protocol interference.
- **Read-only by default** — 7 reading tools; the optional `wechat_send` tool is not even
  registered unless you explicitly enable it in config.
- **Local only** — everything runs on your machine. Data leaves your machine only through the
  AI client you connect (see [Privacy & responsible use](#privacy--responsible-use)).

## How it works

```
WeChat desktop (Weixin.exe, 4.1.12+ / tested 4.1.15.56)
   │  local encrypted SQLite (SQLCipher4) in xwechat_files/
   │  key: read-only memory scan of the logged-in process
   ▼
wechat_reader_mcp/wx_client.py        (adapter: sessions / history / live listener / send)
   ▼
wechat_reader_mcp/server.py           (MCP server, official MCP Python SDK, stdio or SSE)
   ▼
Any MCP client  ──►  AI calls tools: wechat_status / wechat_read / ...
```

## Requirements

| | |
|---|---|
| OS | Windows 10/11 |
| Python | 3.10 – 3.12 on PATH (or the `py` launcher) |
| WeChat | Desktop client **4.1.12+**, logged in while reading (the key lives in the process memory) |
| Network | Only for `pip install` (Tsinghua mirror by default) |

## Quick start (one click)

```
double-click  install.bat
```

`install.bat` is idempotent. It will:

1. create `.venv\` and install dependencies (`wechatauto-replica`, `mcp`),
2. add a tkinter stub if your base Python lacks tcl/tk,
3. **auto-register** the server into every AI client it detects (see table below),
4. run an end-to-end self-test (MCP handshake → tool list → connect WeChat → read).

Then **restart your AI client / open a new session** — done.

### Manual / headless equivalent

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe register_mcp.py
.venv\Scripts\python.exe test_client.py
```

## AI-native usage

This project is designed to be operated by AI agents, not just humans.

- [`AGENTS.md`](AGENTS.md) is the machine-facing entry point: task-oriented commands,
  conventions, and rules for any agent that opens this folder.
- `install.bat` writes an `.agents/mcp.json` into this folder, so agents that support
  workspace-scope MCP auto-connect the moment they open this directory.
- Deterministic verification: `test_client.py` exits `0`/`1` and prints a checklist —
  an agent can self-verify without human judgement.

Tell your AI agent, e.g.:

> Run `wechat-reader-mcp\install.bat`, then verify with `wechat_status` and summarize my
> 5 most recent sessions via `wechat_sessions`.

> Listen to the chat "Alice" (`wechat_listen_add`) and poll `wechat_listen_poll(wait_seconds=20)`
> until she replies, then summarize the conversation.

## MCP tools (7 read-only + optional send)

| Tool | Description |
|---|---|
| `wechat_status` | Connection state, WeChat client version, my account, listeners, buffered new-message count. First call connects (key scan takes a few seconds; WeChat must be logged in). |
| `wechat_sessions(query?)` | Recent chat list with unread counts; with `query`, also appends matching contacts. |
| `wechat_read(chat, limit=30, offset=0)` | Read chat history, ascending by time; increase `offset` for older pages. `chat` = remark / nickname / group name / username (`filehelper` = File Transfer). |
| `wechat_contacts(keyword)` | Search contacts & groups; returned `username` feeds directly into `wechat_read`. |
| `wechat_listen_add(chat)` | Start live monitoring of a chat (persisted; restored on restart). |
| `wechat_listen_poll(wait_seconds=0, chat?)` | Fetch buffered new messages; may block waiting (e.g. `wait_seconds=20` to await a reply). |
| `wechat_listen_remove(chat)` | Stop monitoring a chat. |
| `wechat_send` *(not registered by default)* | Only exists if `"allow_send": true` in config. Requires an unlocked desktop and a visible WeChat window. |

Typical AI flow: `wechat_status` → `wechat_sessions` → `wechat_read` →
`wechat_listen_add` + `wechat_listen_poll(wait_seconds=20)`.

## Where it registers

`register_mcp.py` (idempotent, safe-merging; `--remove` undoes everything):

| Target | Config file | Shape |
|---|---|---|
| ZCode (user scope, all workspaces) | `~/.zcode/cli/config.json` | `mcp.servers` |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` |
| This folder (agents opening it auto-connect) | `<project>/.agents/mcp.json` | `mcpServers` |

Clients not on this list: use `command` = `<project>\.venv\Scripts\python.exe`,
`args` = `["<project>\wechat_reader_mcp\server.py"]`. For URL-based clients run
`run_sse.bat` → `http://127.0.0.1:8790/sse`.

## Configuration

`wechat_reader_mcp\config.json` — generated on first run; all keys optional.

| Key | Default | Meaning |
|---|---|---|
| `allow_send` | `false` | `true` registers the `wechat_send` tool |
| `listen_chats` | `[]` | Chats auto-restored at startup (written by `wechat_listen_add`) |
| `poll_wait_max` | `25` | Max blocking seconds for `wechat_listen_poll` |

## Lifecycle

| Action | Command |
|---|---|
| Install / repair / **update dependencies** | re-run `install.bat` (idempotent) |
| Register / refresh after moving the folder | `.venv\Scripts\python.exe register_mcp.py` |
| Verify | `.venv\Scripts\python.exe test_client.py` (exit 0 = OK) |
| Deregister + remove venv | `uninstall.bat` |
| Remove everything | `uninstall.bat`, then delete the folder |

Configs store absolute paths — after moving the project, re-run `register_mcp.py`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "连接微信数据库失败" / connect error | WeChat desktop is not running or not logged in. Log in, retry — no restart needed. |
| "未找到会话「xx」" | The name must exactly match the remark/nickname in WeChat. Call `wechat_sessions` first; use `filehelper` for File Transfer. |
| tkinter ImportError | Base Python lacks tcl/tk; `install.bat` installs a stub automatically. |
| pip slow / fails | Mirror is preconfigured; alternatively `https://mirrors.aliyun.com/pypi/simple/`. |
| Reading broke after a WeChat upgrade | A major WeChat version change can break DB/key compatibility. Pin/upgrade `wechatauto-replica` and retry. |

## Privacy & responsible use

- This is **not an official WeChat integration**. WeChat ships no personal-account API; local
  database encryption is an intentional boundary set by Tencent. This tool decrypts *your own
  data on your own machine*. Strictly speaking it violates the WeChat ToS; the read path is
  purely local (no injection, no protocol tampering) and practically invisible to the server
  side, while the **send** path (off by default) is server-visible and is where account bans
  actually concentrate. If you enable it, keep it low-frequency and human-like.
- The MCP server keeps data on your machine. Whatever the connected AI client does with the
  content it reads (e.g. uploading context to a cloud model) is that client's behavior —
  connect only clients you trust.
- This tool is a master key to all your chat history: anyone with access to your logged-in
  machine can read everything. Lock your machine.
- Use for personal purposes only. Do not redistribute or resell anyone's chat data.

## Project layout

```
wechat-reader-mcp/
├── install.bat          one-click: venv → deps → stub → register → self-test (idempotent)
├── uninstall.bat        deregister + remove .venv
├── register_mcp.py      register/remove server config in AI clients (--remove, --target, --name)
├── test_client.py       end-to-end self-test (exit code 0/1)
├── prepare_stub.py      tkinter stub for tcl/tk-less Pythons (auto-invoked)
├── run_sse.bat          optional SSE mode on http://127.0.0.1:8790/sse
├── requirements.txt     wechatauto-replica + mcp
├── README.md / README_cn.md / AGENTS.md / LICENSE
└── wechat_reader_mcp/
    ├── server.py        MCP server (7 read-only tools + optional send)
    ├── wx_client.py     WeChat adapter (DB decrypt read, listener, UIA send)
    └── config.json      runtime config (generated, gitignored)
```

## License

[MIT](LICENSE). Underlying libraries: [wechatauto-replica](https://pypi.org/project/wechatauto-replica/)
and the [MCP Python SDK](https://pypi.org/project/mcp/) (both MIT).
