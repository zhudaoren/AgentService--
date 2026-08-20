@echo off
REM AgentService start services via cmd (detached processes survive console close)
setlocal

set "PYTHON=C:\Users\zhudaoren\.conda\envs\AgentService\python.exe"
set "ROOT=%~dp0..\services"
set "LOGDIR=%~dp0..\logs"
set "SHARED=%~dp0..\services\shared"
set "PYTHONPATH=%SHARED%;."
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

if not exist "%PYTHON%" (echo PYTHON NOT FOUND: %PYTHON% & exit /b 1)

pushd "%ROOT%\gateway"
start "gateway"  /B /MIN cmd /c ""%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8000 >> "%LOGDIR%\gateway-cmd.log" 2>&1"
echo gateway started

pushd "%ROOT%\agent-svc"
start "agent-svc" /B /MIN cmd /c ""%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8001 >> "%LOGDIR%\agent-svc-cmd.log" 2>&1"
echo agent-svc started

pushd "%ROOT%\chat-svc"
start "chat-svc" /B /MIN cmd /c ""%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8002 >> "%LOGDIR%\chat-svc-cmd.log" 2>&1"
echo chat-svc started

pushd "%ROOT%\tool-svc"
start "tool-svc" /B /MIN cmd /c ""%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8003 >> "%LOGDIR%\tool-svc-cmd.log" 2>&1"
echo tool-svc started

pushd "%ROOT%\mem-svc"
start "mem-svc" /B /MIN cmd /c ""%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8004 >> "%LOGDIR%\mem-svc-cmd.log" 2>&1"
echo mem-svc started

pushd "%ROOT%\rag-svc"
start "rag-svc" /B /MIN cmd /c ""%PYTHON%" -m uvicorn main:app --host 0.0.0.0 --port 8005 >> "%LOGDIR%\rag-svc-cmd.log" 2>&1"
echo rag-svc started

popd
popd
popd
popd
popd
popd

endlocal
exit /b 0
