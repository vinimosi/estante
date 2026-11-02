@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalando a Estante
set PY=python
where py >nul 2>nul && set PY=py
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Nao encontrei o Python neste computador.
  echo  Baixe em https://www.python.org/downloads/ e, na instalacao,
  echo  marque a opcao "Add python.exe to PATH". Depois abra este arquivo de novo.
  echo.
  pause
  exit /b
)
echo.
echo  Instalando os componentes da Estante, leva menos de um minuto...
%PY% -m pip install --user --quiet --disable-pip-version-check flask psutil pillow
if errorlevel 1 (
  echo  Algo deu errado na instalacao. Confira sua internet e tente de novo.
  pause
  exit /b
)
%PY% -m pip install --user --quiet --disable-pip-version-check pystray >nul 2>nul
rem para o "Tocando agora" ler o painel de midia do Windows (pacotes pequenos)
%PY% -m pip install --user --quiet --disable-pip-version-check winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Storage.Streams >nul 2>nul
%PY% instalar.py
if errorlevel 1 (
  pause
  exit /b
)
timeout /t 4 >nul
