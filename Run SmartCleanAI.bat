@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Khong tim thay .venv. Chay py -3.11 -m venv .venv de khoi tao.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "app.py"
