@echo off
chcp 65001 >nul
title Compilar Instalador Oficial - CMaker Photo Commander
echo ============================================================
echo   Compilando Instalador Windows (Inno Setup)
echo ============================================================
echo.
python "%~dp0build_installer.py"
echo.
pause

