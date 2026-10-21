@echo off
setlocal
set RUNTIME=D:\app\linkmind-runtime

"%RUNTIME%\pg-env\Library\bin\pg_ctl.exe" status -D "%RUNTIME%\pgdata" >nul 2>&1
if errorlevel 1 (
    echo Starting PostgreSQL...
    "%RUNTIME%\pg-env\Library\bin\pg_ctl.exe" -D "%RUNTIME%\pgdata" -l "%RUNTIME%\pg.log" -w start
) else (
    echo PostgreSQL is already running.
)
