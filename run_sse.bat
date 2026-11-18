@echo off
rem Optional: run the MCP server in SSE mode for clients that use URL (Cherry Studio etc.)
chcp 65001 >nul
cd /d "%~dp0"
echo SSE endpoint: http://127.0.0.1:8790/sse
echo (WeChat must stay logged in; keep this window open)
".venv\Scripts\python.exe" "wechat_reader_mcp\server.py" --sse
pause
