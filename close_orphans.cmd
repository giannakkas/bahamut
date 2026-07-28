@echo off
REM ============================================================
REM  Bahamut - close orphaned Binance TESTNET futures positions
REM
REM  Every path is absolute so this works from any shell, with a
REM  stale PATH, or by double-clicking. Do NOT run as Administrator:
REM  an elevated token cannot reach the roaming AppData\npm folder.
REM
REM  Shows a DRY RUN first, then asks before sending anything.
REM ============================================================
setlocal

set "RAILWAY=%APPDATA%\npm\railway.cmd"
set "BACKEND=C:\Users\c.giannakkas\GitHub\bahamut\backend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "SCRIPT=%BACKEND%\scripts\close_orphan_positions.py"

if not exist "%RAILWAY%" (
  echo ERROR: Railway CLI not found at "%RAILWAY%"
  echo If you are running this as Administrator, close it and run as your normal user.
  pause
  exit /b 1
)

cd /d "%BACKEND%"

echo.
echo ===================== DRY RUN =====================
echo Nothing is sent to the exchange in this step.
echo.
call "%RAILWAY%" run --service WORKER -- "%PY%" "%SCRIPT%"

echo.
echo ===================================================
set /p CONFIRM="Close the orphan positions listed above? Type YES to proceed: "
if /i not "%CONFIRM%"=="YES" (
  echo Aborted. Nothing was closed.
  pause
  exit /b 0
)

echo.
echo ==================== EXECUTING ====================
call "%RAILWAY%" run --service WORKER -- "%PY%" "%SCRIPT%" --execute

echo.
echo Done.
pause
endlocal
