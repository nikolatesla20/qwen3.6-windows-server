@echo off
REM =====================================================================
REM  PP=2 + ngram spec-decode variant.
REM  Uses GPU0 + GPU1 to enable ctx=96k. Trades MTP (and some tok/s) for
REM  a much bigger context window. Listens on :5002 — can run alongside
REM  the 72 tok/s baseline on :5001.
REM =====================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
REM Both GPUs exposed; start_pp2.py sets this again to be explicit.
set CUDA_VISIBLE_DEVICES=0,1

set "PY=%VLLM_WINDOWS_VENV%\Scripts\python.exe"
if "%VLLM_WINDOWS_VENV%"=="" set "PY=%~dp0..\venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\python\python.exe"
"%PY%" -u "%~dp0start_pp2.py"
endlocal
