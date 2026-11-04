@echo off
chcp 65001 >nul
title Enviar Projeto para o GitHub - CMaker Photo Commander
echo ============================================================
echo   Enviando Projeto para o GitHub (Espaco-CMaker)
echo ============================================================
echo.
echo Repositório: https://github.com/Espaco-CMaker/SistemaBackupFotos.git
echo Branch:      main
echo.
echo Enviando commits...
git push -u origin main
echo.
if %ERRORLEVEL% EQU 0 (
    echo ============================================================
    echo  ✔ PROJETO ENVIADO COM SUCESSO PARA O GITHUB!
    echo ============================================================
) else (
    echo ============================================================
    echo  [!] Falha no envio. Se uma janela do navegador abriu,
    echo  conclua a autorizacao da sua conta do GitHub e tente de novo.
    echo ============================================================
)
echo.
pause
