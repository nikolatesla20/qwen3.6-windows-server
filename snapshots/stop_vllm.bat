@echo off
REM stop_vllm.bat — kill any vLLM server on ports 5000-5010 + sweep EngineCore/APIServer children
cd /d "%~dp0"
set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"
"%PY%" "%~dp0stop_vllm.py"
