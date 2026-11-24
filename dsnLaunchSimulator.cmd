@echo off
setlocal
cd /d "%~dp0"
if defined DSN_PYTHON (
  "%DSN_PYTHON%" "%~dp0dsnSimulator.py"
  goto finished
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0dsnSimulator.py"
  goto finished
)
where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0dsnSimulator.py"
  goto finished
)
echo Python 3 with Tkinter is needed. No installer or download has been started.
echo Set DSN_PYTHON to an existing Python executable, or use the prepared local launcher.
pause
exit /b 1
:finished
if errorlevel 1 pause
