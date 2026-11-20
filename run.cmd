@echo off
rem AMMDS backup package template repo - Windows entry point.
rem Usage: run.cmd init ^| todo ^| build ^| verify ^<zip^> ^| report ^| selftest
setlocal
set PYTHONIOENCODING=utf-8
python "%~dp0tools\auto_backup.py" %*
exit /b %ERRORLEVEL%
