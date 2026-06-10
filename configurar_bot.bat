@echo off
cd /d "%~dp0"
echo Instalando requests si hace falta...
py -m pip install requests
py configurar_bot.py
pause
