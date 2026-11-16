@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3.13 -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto fail
".venv\Scripts\python.exe" scripts\install_ai.py
if errorlevel 1 goto fail
pause
exit /b 0
:fail
echo Falha ao preparar a IA local. Confira a mensagem e logs\ollama-server.log.
pause
exit /b 1
