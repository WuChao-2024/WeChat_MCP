# wechat-reader-mcp

自包含、**以读取为主**的微信 **MCP（Model Context Protocol）** Server：把本机微信桌面端的消息
暴露给任何支持 MCP 的 AI 客户端（ZCode、Claude Desktop、Cursor、Cherry Studio 等）。
一键安装、一键注册，剩下的交给 AI。

**English docs: [README.md](README.md)**

- **真实数据，非截图** —— 通过解密本地微信数据库（SQLCipher）读取消息；密钥来自对运行中微信进程的
  **只读内存扫描**：不注入 DLL、不修改进程、不干扰网络协议
- **默认只读** —— 7 个读取工具；可选的 `wechat_send` 工具默认**不注册**，需在配置里显式开启
- **纯本地** —— 全部在本机运行。数据只可能经由你接入的 AI 客户端离开本机（见
  [隐私与责任使用](#隐私与责任使用)）

## 工作原理

```
微信桌面端 (Weixin.exe, 4.1.12+ / 已实测 4.1.15.56)
   │  本地加密 SQLite（SQLCipher4），位于 xwechat_files/
   │  密钥：对已登录进程的只读内存扫描
   ▼
wechat_reader_mcp/wx_client.py        （接入层：会话 / 历史 / 实时监听 / 发送）
   ▼
wechat_reader_mcp/server.py           （MCP server，官方 MCP Python SDK，stdio 或 SSE）
   ▼
任意 MCP 客户端 ──► AI 调用工具：wechat_status / wechat_read / ...
```

## 环境要求

| | |
|---|---|
| 操作系统 | Windows 10/11 |
| Python | 3.10 – 3.12（PATH 里有 `python`，或装了 `py` 启动器） |
| 微信 | 桌面端 **4.1.12+**，读取期间保持登录（密钥在进程内存中） |
| 网络 | 仅安装依赖时需要（默认走清华镜像） |

## 一键开始

```
双击 install.bat
```

`install.bat` 可重复执行（幂等），它会：

1. 创建 `.venv\` 并安装依赖（`wechatauto-replica`、`mcp`），
2. 若基础 Python 缺 tcl/tk 则自动补 tkinter 桩模块，
3. **自动注册**到检测到的每一个 AI 客户端（见下表），
4. 跑一遍端到端自检（MCP 握手 → 工具列表 → 连接微信 → 读取）。

然后**重启 AI 客户端 / 新开会话**即可。

### 手动等价流程（无界面环境）

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe register_mcp.py
.venv\Scripts\python.exe test_client.py
```

## AI Native（给 AI 用）

本项目按「AI 可自主操作」设计：

- [`AGENTS.md`](AGENTS.md) 是面向机器的入口：任务化命令、约定与规则，任何 Agent 打开本文件夹即可照做
- `install.bat` 会在本目录生成 `.agents/mcp.json`，支持工作区级 MCP 的客户端**打开本目录即自动连接**
- 可自验证：`test_client.py` 退出码 0/1 + 检查清单输出，Agent 无需人工判断

对 AI 说一句话即可，例如：

> 运行 `wechat-reader-mcp\install.bat`，然后用 wechat_status 验证，再用 wechat_sessions
> 汇总我最近 5 个会话。

> 用 wechat_listen_add 监听「张三」，循环 wechat_listen_poll(wait_seconds=20) 等他回复，
> 然后总结这段对话。

## MCP 工具（7 个只读 + 可选发送）

| 工具 | 说明 |
|---|---|
| `wechat_status` | 连接状态 / 微信版本 / 我的账号 / 监听列表 / 待取新消息数。首次调用会连接微信（密钥扫描约几秒，需已登录） |
| `wechat_sessions(query?)` | 最近会话列表（含未读数）；带 query 时附带联系人搜索结果 |
| `wechat_read(chat, limit=30, offset=0)` | 读聊天记录（时间升序；offset 增大翻更早）。chat=备注/昵称/群名/username（`filehelper`=文件传输助手） |
| `wechat_contacts(keyword)` | 搜索联系人/群；返回的 username 可直接传给 `wechat_read` |
| `wechat_listen_add(chat)` | 开始实时监听某会话（持久化，重启自动恢复） |
| `wechat_listen_poll(wait_seconds=0, chat?)` | 取缓冲的新消息；可阻塞等待（如 `wait_seconds=20` 等对方回复） |
| `wechat_listen_remove(chat)` | 停止监听某会话 |
| `wechat_send`（默认不注册） | 仅当 config `"allow_send": true` 才存在；需桌面解锁且微信窗口可见 |

AI 典型流程：`wechat_status` → `wechat_sessions` → `wechat_read` →
`wechat_listen_add` + `wechat_listen_poll(wait_seconds=20)`。

## 注册到哪些位置

`register_mcp.py`（幂等、安全合并已有配置；`--remove` 全部撤销）：

| 目标 | 配置文件 | 结构 |
|---|---|---|
| ZCode（用户级，所有工作区） | `~/.zcode/cli/config.json` | `mcp.servers` |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `mcpServers` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers` |
| 本文件夹（AI 打开即连） | `<项目>/.agents/mcp.json` | `mcpServers` |

不在表里的客户端：`command` = `<项目>\.venv\Scripts\python.exe`，
`args` = `["<项目>\wechat_reader_mcp\server.py"]`。URL 型客户端用 `run_sse.bat` →
`http://127.0.0.1:8790/sse`。

## 配置

`wechat_reader_mcp\config.json`（首次运行自动生成，所有键可省略）：

| 键 | 默认 | 含义 |
|---|---|---|
| `allow_send` | `false` | `true` 时注册 `wechat_send` 发送工具 |
| `listen_chats` | `[]` | 启动自动恢复的监听（`wechat_listen_add` 自动写入） |
| `poll_wait_max` | `25` | `wechat_listen_poll` 最大阻塞秒数 |

## 生命周期

| 动作 | 命令 |
|---|---|
| 安装 / 修复 / **升级依赖** | 重跑 `install.bat`（幂等） |
| 注册 / 移动目录后刷新 | `.venv\Scripts\python.exe register_mcp.py` |
| 验证 | `.venv\Scripts\python.exe test_client.py`（退出码 0 = 正常） |
| 注销 + 删除 venv | `uninstall.bat` |
| 彻底移除 | `uninstall.bat` 后删除整个文件夹 |

注册配置存绝对路径——项目移动位置后需重跑 `register_mcp.py`。

## 常见问题

| 现象 | 处理 |
|---|---|
| 「连接微信数据库失败」 | 微信桌面端没开或未登录；登录后重试即可（无需重启 server） |
| 「未找到会话「xx」」 | 名称须与微信里的备注/昵称完全一致；先 `wechat_sessions` 查；文件传输助手用 `filehelper` |
| tkinter ImportError | 基础 Python 缺 tcl/tk；`install.bat` 已自动放桩模块 |
| pip 慢/失败 | 已预配清华镜像；可换阿里 `https://mirrors.aliyun.com/pypi/simple/` |
| 微信升级后读取失效 | 大版本更新可能破坏数据库/密钥兼容性；升级 `wechatauto-replica` 后重试 |

## 隐私与责任使用

- 本项目**不是微信官方集成**。微信没有个人号 API，本地库加密是腾讯刻意设置的边界；本工具做的是
  「解密自己电脑上自己的数据」，严格说违反微信用户协议。读取为纯本地行为（无注入、不碰协议），
  服务端侧实际不可见；而**发送**路径（默认关闭）在服务端可见，是封号风险集中区——若开启请保持
  低频、拟人节奏
- MCP server 本身数据不出本机；接入的 AI 客户端读走内容后的行为（如上传上下文到云端模型）由该
  客户端决定——只接入你信任的客户端
- 本工具等于「能读全部聊天记录的钥匙」：任何能接触你登录中电脑的人都能读你的记录，请锁好电脑
- 仅供个人使用；不得对外提供、转售任何人的聊天数据

## 目录结构

```
wechat-reader-mcp/
├── install.bat          一键：venv → 依赖 → 桩 → 注册 → 自检（幂等）
├── uninstall.bat        注销 + 删除 .venv
├── register_mcp.py      注册/移除各 AI 客户端配置（--remove / --target / --name）
├── test_client.py       端到端自检（退出码 0/1）
├── prepare_stub.py      tkinter 桩（自动调用）
├── run_sse.bat          可选 SSE 模式 http://127.0.0.1:8790/sse
├── requirements.txt     wechatauto-replica + mcp
├── README.md / README_cn.md / AGENTS.md / LICENSE
└── wechat_reader_mcp/
    ├── server.py        MCP server（7 个只读工具 + 可选发送）
    ├── wx_client.py     微信接入层（数据库解密读 / 监听 / UIA 发送）
    └── config.json      运行时配置（自动生成，已 gitignore）
```

## 许可

[MIT](LICENSE)。底层依赖：[wechatauto-replica](https://pypi.org/project/wechatauto-replica/)
与 [MCP Python SDK](https://pypi.org/project/mcp/)（均为 MIT）。
