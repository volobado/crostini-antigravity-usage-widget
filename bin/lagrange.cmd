@echo off
:: Lagrange CLI, runnable straight from a clone (no install step).
::   lagrange run [agy args]   run Antigravity so account switches apply in place
::   lagrange doctor           diagnose
::   lagrange list | add | switch <email> | forget <email>
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%;%PYTHONPATH%"

if defined LAGRANGE_PYTHON (
  set "PY=%LAGRANGE_PYTHON%"
) else (
  set "PY=py -3"
  where py >nul 2>&1 || set "PY=python"
)

%PY% -m lagrange %*
exit /b %ERRORLEVEL%
