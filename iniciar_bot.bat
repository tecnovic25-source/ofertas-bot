@echo off
cd /d "%~dp0"
echo Instalando dependencias...
py -m pip install -r requirements.txt

echo Instalando Chromium de Playwright...
py -m playwright install chromium

echo Iniciando bot...
py app.py
pause
