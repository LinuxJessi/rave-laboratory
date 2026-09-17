@echo off
rem Rave Laboratory with a console window (shows errors and --bench output). Double-click "Rave Laboratory.pyw" for no console.
cd /d "%~dp0"
if exist "runtime\python.exe" (
    "runtime\python.exe" ravelab.py %*
    if errorlevel 1 pause
    goto :end
)
where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 was not found. Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),
    echo or download the ready-made Rave Laboratory build, which needs no Python.
    pause
    goto :end
)
python -c "import pygame" >nul 2>nul || python -m pip install -r requirements.txt
python ravelab.py %*
if errorlevel 1 pause
:end
