@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (py -3 vocabulary_app\server.py %* & goto :eof)
python vocabulary_app\server.py %*
