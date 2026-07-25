@echo off
setlocal
setlocal EnableDelayedExpansion
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
  --add-data "prototypes\hyperframes;prototypes\hyperframes" ^
  app.py

if not exist "dist\AI Handoff Builder\bin" mkdir "dist\AI Handoff Builder\bin"
call :copy_tool ffmpeg.exe
call :copy_tool ffprobe.exe
set "EXIFTOOL_SRC="
if exist "bin\exiftool.exe" set "EXIFTOOL_SRC=%cd%\bin\exiftool.exe"
if not defined EXIFTOOL_SRC (
  for /f "delims=" %%P in ('where exiftool.exe 2^>nul') do (
    if not defined EXIFTOOL_SRC set "EXIFTOOL_SRC=%%P"
  )
)
if not defined EXIFTOOL_SRC (
  echo WARNING: exiftool.exe not found. Put it in bin\ for portable metadata extraction.
) else (
  copy /Y "%EXIFTOOL_SRC%" "dist\AI Handoff Builder\bin\exiftool.exe" >nul
  set "EXIFTOOL_ROOT=%cd%\bin\exiftool_files"
  if not exist "!EXIFTOOL_ROOT!" (
    for %%D in ("%EXIFTOOL_SRC%\..") do set "EXIFTOOL_ROOT=%%~fD\exiftool_files"
  )
  if exist "!EXIFTOOL_ROOT!" (
    robocopy "!EXIFTOOL_ROOT!" "dist\AI Handoff Builder\bin\exiftool_files" /E /NFL /NDL /NJH /NJS /NC /NS >nul
    if errorlevel 8 (
      echo WARNING: robocopy failed to copy exiftool_files. Metadata extraction may fall back at runtime.
    )
  ) else (
    echo WARNING: exiftool_files folder not found next to exiftool.exe. Metadata extraction may fall back at runtime.
  )
)

echo.
echo EXE created in dist\AI Handoff Builder\
echo Runtime tools should be available in dist\AI Handoff Builder\bin\
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
