@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 goto usepy
python server.py --open
goto done
:usepy
py -3 server.py --open
:done
if errorlevel 1 pause
