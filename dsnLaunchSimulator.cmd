@echo off
setlocal
cd /d "%~dp0"
if not defined DSN_PYTHON if exist "%~dp0..\dsnPython314\python.exe" set "DSN_PYTHON=%~dp0..\dsnPython314\python.exe"
if defined DSN_PYTHON (
  for %%I in ("%DSN_PYTHON%") do set "DSN_PYTHON_HOME=%%~dpI"
  call :tkpaths
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
exit /b
:tkpaths
if exist "%DSN_PYTHON_HOME%tcl\tcl_library\init.tcl" set "TCL_LIBRARY=%DSN_PYTHON_HOME%tcl\tcl_library"
if exist "%DSN_PYTHON_HOME%tcl\tk_library\tk.tcl" set "TK_LIBRARY=%DSN_PYTHON_HOME%tcl\tk_library"
exit /b
