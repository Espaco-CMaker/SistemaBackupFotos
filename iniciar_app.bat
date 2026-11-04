@echo off
chcp 65001 >nul
title CMaker Photo Commander
echo ============================================================
echo   Iniciando CMaker Photo Commander
echo ============================================================
echo.
if exist "%~dp0CMakerPhotoCommander.exe" (
    start "" "%~dp0CMakerPhotoCommander.exe"
    exit /b 0
)
python "%~dp0scripts\app_gui.py"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocorreu um erro ao executar a aplicacao. Pressione qualquer tecla para sair...
    pause >nul
)

