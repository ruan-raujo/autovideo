@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente Python local...
    py -3.13 -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto fail
echo.
echo AutoVideo AI - http://127.0.0.1:8000
echo Mantenha esta janela aberta. Para encerrar, pressione Ctrl+C.
".venv\Scripts\python.exe" scripts\run.py
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo Nao foi possivel iniciar. Confira a mensagem acima e o README.md.
pause
exit /b 1
