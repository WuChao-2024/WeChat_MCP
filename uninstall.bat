@echo off
rem ============================================================
rem  wechat-reader-mcp uninstaller
rem  1) deregisters the MCP server from all AI clients
rem  2) removes the local virtualenv
rem  To remove everything: afterwards delete this folder.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] Deregistering from AI clients ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" register_mcp.py --remove
) else (
    python register_mcp.py --remove 2>nul || echo        no python available - remove MCP entries manually
)

echo [2/2] Removing .venv ...
if exist ".venv" rmdir /s /q ".venv"

echo.
echo Done. Chat data was never stored by this project.
echo To delete the project itself, remove this folder.
pause
