@echo off
:: Open the Lagrange widget without a console window.
:: Safe to call from every launcher: a second run raises the existing window
:: instead of opening another one.
setlocal
set "REPO=%~dp0.."
set "PYTHONPATH=%REPO%;%PYTHONPATH%"

if defined LAGRANGE_PYTHONW (
  set "PYW=%LAGRANGE_PYTHONW%"
) else (
  set "PYW=pythonw.exe"
)

start "" /b "%PYW%" -m lagrange widget
