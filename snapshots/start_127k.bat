@echo off
REM start_127k.bat — GPU1 mem=0.948 ctx=127k (max single-GPU MTP n=3, 350W)
cd /d "%~dp0"
set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"
"%PY%" start_127k.py
