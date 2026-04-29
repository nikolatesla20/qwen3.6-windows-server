@echo off
REM =====================================================================
REM  Tool-calling-fixed snapshot (PR #35687 + #40861 + enhanced.jinja)
REM  Qwen3.6-27B Lorbus AutoRound INT4 — TP=1 GPU1 MTP n=3 ctx=64k port=5005
REM =====================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

if not defined WT_SESSION (
    set "WT_EXE=C:\Program Files\WindowsTerminal\wt.exe"
    if exist "!WT_EXE!" (
        "!WT_EXE!" -d "%~dp0." cmd /k """%~f0"""
        exit /b 0
    )
)

if "%VLLM_WINDOWS_VENV%"=="" set "VLLM_WINDOWS_VENV=%~dp0..\venv"

"%VLLM_WINDOWS_VENV%\Scripts\python.exe" -u "%~dp0start_toolcall.py"
endlocal
