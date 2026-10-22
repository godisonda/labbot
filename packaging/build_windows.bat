@echo off
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите Python 3.10+ с python.org и повторите.
  pause
  exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

python -m PyInstaller packaging\labbot.spec --noconfirm --clean
if errorlevel 1 goto :error

echo.
echo Готово: dist\LabBot\LabBot.exe
echo При первом запуске создастся папка %%USERPROFILE%%\Documents\LabBot (labs, settings.json, .env)
pause
exit /b 0

:error
echo.
echo Сборка не удалась — смотрите сообщения выше.
pause
exit /b 1
