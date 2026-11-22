@echo off
chcp 65001 > nul
cd /d "%~dp0.."
"%~dp0..\.venv\Scripts\python.exe" "%~dp0build_mobile_keygen.py"
pause
