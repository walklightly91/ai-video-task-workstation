@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "BOOTSTRAP_PY="

for %%P in ("%LocalAppData%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python311\python.exe" "%ProgramFiles(x86)%\Python311\python.exe") do (
  if not defined BOOTSTRAP_PY if exist "%%~fP" set "BOOTSTRAP_PY=%%~fP"
)
if not defined BOOTSTRAP_PY (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,11) else 1)" >nul 2>nul
  if not errorlevel 1 set "BOOTSTRAP_PY=python"
)
if not defined BOOTSTRAP_PY (
  echo Python 3.11 was not found. Install Python 3.11 for the current user, then run this file again.
  pause
  exit /b 1
)

echo VideoTaskHub complete non-admin installation
echo This creates project-only environments and installs the main runtime, FFmpeg, Seed-VC and CPU/CUDA PyTorch.
"%BOOTSTRAP_PY%" bootstrap_install.py %*
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" echo Installation failed. Keep this window open and send the displayed error log to support.
if "%RESULT%"=="0" echo Main program installed. Check above for optional FFmpeg or Seed-VC warnings; then run 运行-dev.bat.
pause
exit /b %RESULT%
