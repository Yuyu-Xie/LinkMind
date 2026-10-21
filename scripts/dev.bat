@echo off
setlocal
set RUNTIME=D:\app\linkmind-runtime
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."

if not exist "%RUNTIME%\logs" mkdir "%RUNTIME%\logs"

echo Starting Huey consumer in a new window...
start "LinkMind Huey" "%RUNTIME%\venv\Scripts\python.exe" manage.py run_huey --logfile "%RUNTIME%\logs\huey.log"

echo Starting Django dev server on http://127.0.0.1:8000 ...
"%RUNTIME%\venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
