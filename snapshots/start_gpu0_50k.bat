@echo off
set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"
"%PY%" "%~dp0start_gpu0_50k.py" %*
