@echo off
cd /d %~dp0
start "" .venv\Scripts\pythonw -m healthcheck gui --demo
