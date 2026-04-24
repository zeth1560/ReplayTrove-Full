@echo off
setlocal EnableDelayedExpansion
REM ReplayTrove Control Center — one-click start (API + Vite UI) and open browser.
REM Double-click from Explorer. Repo root = this file's directory (override with REPLAYTROVE_ROOT).

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

if not "%REPLAYTROVE_ROOT%"=="" set "REPO_ROOT=%REPLAYTROVE_ROOT%"

set "API_PORT=%REPLAYTROVE_CONTROL_CENTER_API_PORT%"
if "!API_PORT!"=="" set "API_PORT=4311"

set "UI_PORT=%REPLAYTROVE_CONTROL_CENTER_UI_PORT%"
if "!UI_PORT!"=="" set "UI_PORT=5173"

set "LOG_DIR=%REPO_ROOT%\state"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul
set "LOG=%LOG_DIR%\control_center_launch.log"

call :logline "======== Control Center launcher ========"
call :logline "REPO_ROOT=!REPO_ROOT!"
call :logline "API_PORT=!API_PORT! UI_PORT=!UI_PORT!"

cd /d "!REPO_ROOT!" 2>nul
if errorlevel 1 (
  call :logline "ERROR: Could not cd to REPO_ROOT"
  echo Could not open repo root: !REPO_ROOT!
  pause
  exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
  call :logline "ERROR: npm not on PATH"
  echo Install Node.js LTS and ensure npm is on your PATH, then try again.
  pause
  exit /b 1
)

if not exist "!REPO_ROOT!\node_modules\" (
  call :logline "node_modules missing - running npm install at repo root (first run may take a minute)."
  call npm install
  if errorlevel 1 (
    call :logline "ERROR: npm install failed"
    echo npm install failed. See messages above.
    pause
    exit /b 1
  )
)

call :ensure_api
call :ensure_ui

call :logline "Waiting briefly for Vite to listen..."
timeout /t 2 /nobreak >nul

set "UI_URL=http://127.0.0.1:!UI_PORT!/"
call :logline "Opening browser: !UI_URL!"
start "" "!UI_URL!"

call :logline "Done. API and UI run in separate minimized windows."
echo.
echo Browser: !UI_URL!
echo API: http://127.0.0.1:!API_PORT!/
echo Log file: !LOG!
echo Close the minimized windows named "npm" / node to stop services.
echo.
pause
exit /b 0

:ensure_api
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -Uri \"http://127.0.0.1:!API_PORT!/api/config\" -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  call :logline "API already running on port !API_PORT! - not starting another."
  goto :eof
)
call :logline "Starting Control Center API (npm run api)..."
set "REPLAYTROVE_LAUNCH_ROOT=!REPO_ROOT!"
powershell -NoProfile -Command "Start-Process -FilePath npm.cmd -ArgumentList @('run','api','--workspace','@replaytrove/control-center') -WindowStyle Minimized -WorkingDirectory $env:REPLAYTROVE_LAUNCH_ROOT"
call :wait_api
goto :eof

:wait_api
set /a "_N=0"
:wait_api_loop
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -Uri \"http://127.0.0.1:!API_PORT!/api/config\" -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  call :logline "API is up."
  goto :eof
)
set /a "_N+=1"
if !_N! GEQ 45 (
  call :logline "WARNING: API did not respond in time. Check minimized npm window or port !API_PORT!."
  goto :eof
)
timeout /t 1 /nobreak >nul
goto :wait_api_loop

:ensure_ui
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -Uri \"http://127.0.0.1:!UI_PORT!/\" -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  call :logline "UI already responding on port !UI_PORT! - not starting another Vite server."
  goto :eof
)
call :logline "Starting Control Center UI (Vite) on 127.0.0.1:!UI_PORT! ..."
set "REPLAYTROVE_LAUNCH_ROOT=!REPO_ROOT!"
set "REPLAYTROVE_LAUNCH_UI_PORT=!UI_PORT!"
powershell -NoProfile -Command "$p=$env:REPLAYTROVE_LAUNCH_UI_PORT; Start-Process -FilePath npm.cmd -ArgumentList @('run','dev','--workspace','@replaytrove/control-center','--','--port',$p,'--host','127.0.0.1') -WindowStyle Minimized -WorkingDirectory $env:REPLAYTROVE_LAUNCH_ROOT"
goto :eof

:logline
set "LINE=%*"
echo [!date! !time!] !LINE!>> "%LOG%"
echo !LINE!
goto :eof
