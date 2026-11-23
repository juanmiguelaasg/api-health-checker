@echo off
cd /d %~dp0
.venv\Scripts\python -m healthcheck watch
pause
