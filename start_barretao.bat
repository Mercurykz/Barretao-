@echo off
cd /d "c:\Users\Administrador\Desktop\Barretão"
title Barretão Hub
:loop
echo [%date% %time%] Iniciando Barretão Hub...
.\.venv311\Scripts\python.exe barretao_hub.py
echo [%date% %time%] Hub encerrou. Reiniciando em 5 segundos...
timeout /t 5 /nobreak >nul
goto loop
