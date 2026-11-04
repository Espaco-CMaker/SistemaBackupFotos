@echo off
chcp 65001 >nul
title Publicar Release e Executaveis no GitHub
echo ============================================================
echo   Publicando Release e Binarios no GitHub Releases
echo ============================================================
echo.
python "%~dp0publish_release.py"
echo.
pause

