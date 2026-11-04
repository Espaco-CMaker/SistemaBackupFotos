@echo off
chcp 65001 >nul
title Compilar Executavel Standalone - CMaker Photo Commander
echo ============================================================
echo   Compilando Executavel Standalone (PyInstaller)
echo ============================================================
echo.
python "%~dp0build_exe.py"
echo.
pause

