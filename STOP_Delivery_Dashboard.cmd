@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0launch_delivery_dashboard.py" --stop
if errorlevel 1 pause
