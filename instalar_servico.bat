@echo off
REM ============================================================
REM  Instala o serviço Windows "SIRESP-Web" via NSSM
REM  Rode como ADMINISTRADOR
REM ============================================================

set SERVICO=SIRESP-Web
set PYTHON=C:\Python312\python.exe
set APP=C:\ProjetoSiresp\servico.py
set DIR=C:\ProjetoSiresp
set NSSM=C:\nssm\nssm.exe

echo.
echo === Instalando servico %SERVICO% ===
echo.

%NSSM% install %SERVICO% "%PYTHON%" "%APP%"
%NSSM% set %SERVICO% AppDirectory "%DIR%"
%NSSM% set %SERVICO% DisplayName "SIRESP - Producao x Profissional + Repasse"
%NSSM% set %SERVICO% Description "Servidor web interno (porta 8001) para SIRESP"
%NSSM% set %SERVICO% Start SERVICE_AUTO_START
%NSSM% set %SERVICO% AppStdout "%DIR%\servico.log"
%NSSM% set %SERVICO% AppStderr "%DIR%\erro_servico.log"
%NSSM% set %SERVICO% AppRotateFiles 1
%NSSM% set %SERVICO% AppRotateBytes 10485760

echo.
echo === Servico instalado. Iniciando... ===
%NSSM% start %SERVICO%

echo.
echo === Status ===
%NSSM% status %SERVICO%

pause