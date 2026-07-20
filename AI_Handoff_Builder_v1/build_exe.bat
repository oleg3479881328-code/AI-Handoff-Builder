@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

pyinstaller --noconfirm --clean --windowed ^
  --name "AI Handoff Builder" ^
  --collect-all PIL ^
  app.py

if not exist "dist\AI Handoff Builder\bin" mkdir "dist\AI Handoff Builder\bin"
call :copy_tool ffmpeg.exe
call :copy_tool ffprobe.exe

echo.
echo EXE created in dist\AI Handoff Builder\
echo FFmpeg tools should be available in dist\AI Handoff Builder\bin\
pause
exit /b 0

:error
echo Build failed.
pause
exit /b 1

:copy_tool
set "TOOL_PATH="
for /f "delims=" %%P in ('where %1 2^>nul') do (
  if not defined TOOL_PATH set "TOOL_PATH=%%P"
)
if defined TOOL_PATH (
  copy /Y "%TOOL_PATH%" "dist\AI Handoff Builder\bin\%1" >nul
) else (
  echo WARNING: %1 not found in PATH. Put it in dist\AI Handoff Builder\bin\
)
exit /b 0
