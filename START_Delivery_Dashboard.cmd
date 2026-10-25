@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0launch_delivery_dashboard.py"
if errorlevel 1 pause
