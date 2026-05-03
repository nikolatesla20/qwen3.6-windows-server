@echo off
REM start_instruct_general.bat - Instruct (non-thinking) general, 127k ctx
cd /d "%~dp0"
set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"
"%PY%" start_instruct_general.py
