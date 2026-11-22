@echo off
rem One-command AeroSwarm demo on Windows: double-click, or run `demo` / `demo -Scenario scenarios\stress_1k.json -NoCheck`.
rem All arguments are passed to scripts\windows\demo.ps1 (see its header for options).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\demo.ps1" %*
if errorlevel 1 pause
