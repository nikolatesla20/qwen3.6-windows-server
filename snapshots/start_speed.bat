@echo off
REM start_speed.bat — GPU1 MTP n=6 ctx=90k mem=0.948 350W — peak decode ~64.5 tok/s
cd /d "%~dp0"
set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"
"%PY%" start_speed.py
