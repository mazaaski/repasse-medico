@echo off
set SERVICO=SIRESP-Web
set NSSM=C:\nssm\nssm.exe

echo Parando servico...
%NSSM% stop %SERVICO%
timeout /t 3 >nul

echo Removendo servico...
%NSSM% remove %SERVICO% confirm

pause