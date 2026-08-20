@echo off
REM Per-service launcher: set PYTHONPATH properly, then launch uvicorn on given port
REM Usage: run_svc.bat <service_dir_name> <port> [log_name_part]
setlocal

set "PYTHON=C:\Users\zhudaoren\.conda\envs\AgentService\python.exe"
set "ROOT=%~dp0..\services"
set "SHARED=%~dp0..\services\shared"

set SVC=%1
set PORT=%2
set LOGNAME=%~3
if "%LOGNAME%"=="" set LOGNAME=%SVC%

set "PYTHONPATH=%SHARED%;."
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

cd /d "%ROOT%\%SVC%"
echo [%DATE% %TIME%] Starting %SVC% on port %PORT% (cwd=%CD%)
"%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port %PORT% 2>&1
set EXIT=%ERRORLEVEL%
echo [%DATE% %TIME%] %SVC% EXITED WITH CODE %EXIT%
exit /b %EXIT%
