@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:5055
"C:\Users\aggan\anaconda3\python.exe" app.py
pause
