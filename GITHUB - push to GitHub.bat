@echo off
rem Sends this folder's history to your private GitHub repository.
rem First time: asks for the repository address. After that it just pushes.
setlocal
cd /d "%~dp0"
where git >nul 2>nul || (echo Git for Windows is not installed. Install it from https://git-scm.com/download/win and run this again. & pause & exit /b 1)
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo.
  echo  1. On github.com click New ^> New repository, name it niagara-station-review, choose Private,
  echo     and leave "Add a README" unticked.
  echo  2. Copy its address, for example https://github.com/yourname/niagara-station-review.git
  echo.
  set /p URL=Paste the repository address here and press Enter: 
  call git remote add origin %%URL%%
)
echo.
echo Pushing to:
git remote get-url origin
git push -u origin main --tags
if errorlevel 1 (
  echo.
  echo The push did not go through - see the message above.
  echo If it says the remote has work you do not have, run "GITHUB - get latest.bat" first.
  pause & exit /b 1
)
echo.
echo Done - GitHub is up to date.
pause
