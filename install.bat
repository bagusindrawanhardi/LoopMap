@echo off
echo Downloading loopmap.exe from GitHub Releases...
curl -L -o "%~dp0loopmap.exe" "https://github.com/bagusindrawanhardi/LoopMap/releases/latest/download/loopmap-windows.exe"
if %errorlevel% neq 0 (
    echo Download failed. Visit https://github.com/bagusindrawanhardi/LoopMap/releases to download manually.
    pause
    exit /b 1
)
echo.
echo Done. loopmap.exe is ready.
echo.
echo Usage:
echo   loopmap.exe --project usecases\^<your-topic^> --serve
echo.
pause
