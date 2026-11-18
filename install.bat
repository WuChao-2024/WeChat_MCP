@echo off
rem ============================================================
rem  wechat-reader-mcp one-click installer
rem  Creates venv, installs deps, registers MCP into AI clients,
rem  then runs an end-to-end self-test.
rem  Requires: Windows, Python 3.10-3.12 on PATH (or py launcher),
rem            WeChat 4.1.12+ desktop client installed.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo [1/5] Checking Python ...
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>nul || (echo [error] Python not found. Install Python 3.10-3.12 first. & pause & exit /b 1)
    set "PY=py -3.12"
)
echo        using: %PY%

echo [2/5] Creating venv + installing dependencies (Tsinghua mirror) ...
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || (echo [error] venv creation failed. & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --no-input
if errorlevel 1 (
    echo [warn] mirror failed, retrying with default PyPI ...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --no-input
)

echo [3/5] Checking tkinter stub (base Python without tcl/tk) ...
".venv\Scripts\python.exe" -c "import tkinter" >nul 2>nul
if errorlevel 1 ".venv\Scripts\python.exe" prepare_stub.py

echo [4/5] Registering MCP server into AI clients ...
".venv\Scripts\python.exe" register_mcp.py

echo [5/5] Self-test (WeChat desktop must be logged in for full check) ...
".venv\Scripts\python.exe" test_client.py

echo.
echo ============================================================
echo  Done. Restart your AI client (or open a new session),
echo  then ask the AI to call: wechat_status / wechat_sessions / wechat_read
echo ============================================================
pause
