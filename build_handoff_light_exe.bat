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

for /f "delims=" %%V in ('python -c "from handoff_builder.handoff_light import APP_BUNDLE_NAME; print(APP_BUNDLE_NAME)"') do set "APP_BUNDLE_NAME=%%V"
if not defined APP_BUNDLE_NAME goto :error

pyinstaller --noconfirm --clean "Handoff Light.spec"
if errorlevel 1 goto :error
if not exist "dist\%APP_BUNDLE_NAME%\bin" mkdir "dist\%APP_BUNDLE_NAME%\bin"

for %%T in (ffmpeg.exe ffprobe.exe exiftool.exe) do call :copy_tool %%T

echo.
echo EXE created in dist\%APP_BUNDLE_NAME%\
pause
exit /b 0

:copy_tool
set "TOOL_PATH="
for /f "delims=" %%P in ('where %1 2^>nul') do (
  if not defined TOOL_PATH set "TOOL_PATH=%%P"
)
if defined TOOL_PATH (
  copy /Y "%TOOL_PATH%" "dist\%APP_BUNDLE_NAME%\bin\%1" >nul
)
exit /b 0

:error
echo Build failed.
pause
exit /b 1
