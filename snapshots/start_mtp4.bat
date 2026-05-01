@echo off
REM start_mtp4.bat — GPU1 MTP n=4 ctx=120k mem=0.948 — best decode TPS (~58)
cd /d "%~dp0"
set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"
"%PY%" start_mtp4.py
