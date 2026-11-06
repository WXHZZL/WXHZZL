@echo off
chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
title FYAgent
cd /d "%~dp0"

rem Prefer the repo-local virtualenv on D: (created by setup.ps1); fall back to PATH python.
set "VENV_PY=%~dp0..\..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" (
  set "PY=%VENV_PY%"
) else (
  set "PY=python"
)

"%PY%" -X utf8 main.py %*
if errorlevel 1 pause
