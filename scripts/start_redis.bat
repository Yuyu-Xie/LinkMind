@echo off
setlocal
set RUNTIME=D:\app\linkmind-runtime

"%RUNTIME%\Memurai\Memurai\memurai-cli.exe" ping >nul 2>&1
if errorlevel 1 (
    echo Starting Memurai...
    start "Memurai" "%RUNTIME%\Memurai\Memurai\memurai.exe" "%RUNTIME%\memurai.conf"
    timeout /t 2 /nobreak >nul
    "%RUNTIME%\Memurai\Memurai\memurai-cli.exe" ping
) else (
    echo Memurai is already running.
)
