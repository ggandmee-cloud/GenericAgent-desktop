@echo off
REM Launcher for windows.ps1 (same directory). Arg1 = manifest.json
setlocal
set "HERE=%~dp0"
set "MANIFEST=%~1"
if "%MANIFEST%"=="" exit /b 2
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERE%windows.ps1" -ManifestPath "%MANIFEST%"
exit /b %ERRORLEVEL%
