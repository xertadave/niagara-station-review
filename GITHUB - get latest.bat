@echo off
rem Brings this folder up to date with GitHub. Your data folder is never touched.
setlocal
cd /d "%~dp0"
where git >nul 2>nul || (echo Git for Windows is not installed. Install it from https://git-scm.com/download/win and run this again. & pause & exit /b 1)
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo.
  echo This folder is not linked to GitHub yet.
  echo Run "GITHUB - push to GitHub.bat" first - it asks for your repository address and sends the code up.
  echo After that, this file brings the folder up to date.
  pause & exit /b 1
)
git pull --ff-only origin main
if errorlevel 1 (echo. & echo Could not update automatically - see the message above. & pause & exit /b 1)
git fetch --tags
echo.
echo Up to date. Restart Station Review to use the new version.
pause
