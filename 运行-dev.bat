@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "WT_PROJECT_VENV_LAUNCHED=1"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist ".venv\Scripts\python.exe" (
  echo The project environment is not installed. Run 安装.bat once first.
  pause
  exit /b 1
)
echo Starting VideoTaskHub. This console is the live debug log.
call ".venv\Scripts\python.exe" "main-dev.py"
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" echo VideoTaskHub exited with code %RESULT%.
pause
exit /b %RESULT%
