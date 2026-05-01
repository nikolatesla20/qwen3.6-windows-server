@echo off
REM =====================================================================
REM  Preserve 72 tok/s baseline: Qwen3.6-27B Lorbus AutoRound INT4
REM  TP=1 PP=1 MTP n=3 fp8_e4m3 TRITON_ATTN ctx=32k GPU1 only
REM  Do not edit start_72tps.py's knobs above without updating this file.
REM =====================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"

"%PY%" -u "%~dp0start_72tps.py"
endlocal
