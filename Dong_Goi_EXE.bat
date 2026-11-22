@echo off
chcp 65001 > nul
cd /d "%~dp0"
set "BASE=%CD%"
if "%BASE:~-1%"=="\" set "BASE=%BASE:~0,-1%"
set "PYINSTALLER_CONFIG_DIR=%BASE%\.pyinstaller"
set "TEMP=%BASE%\build_tmp"
set "TMP=%BASE%\build_tmp"
if not exist "%TEMP%" mkdir "%TEMP%"
echo ======================================================
echo   DANG DONG GOI DUY NHAT 1 FILE: NTQ Remote.exe (v2.0)
echo ======================================================
echo.
set "EXCLUDES=--exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineQuick --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets --exclude-module PySide6.Qt3DCore --exclude-module PySide6.Qt3DRender --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQml --exclude-module PySide6.QtMultimedia"

if not exist "%BASE%\BoCaiDat" mkdir "%BASE%\BoCaiDat"
"%BASE%\.venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed %EXCLUDES% --icon "%BASE%\assets\ntq_remote.ico" --version-file "%BASE%\version_info.txt" --add-data "%BASE%\assets\ntq_remote.ico;assets" --distpath "%BASE%\BoCaiDat" --name "NTQ Remote" --paths "%BASE%" "%BASE%\run_unified.py"
if errorlevel 1 goto :err

if exist "%BASE%\BoCaiDat\CaiDat_PhongTinHocVN.exe" del /f /q "%BASE%\BoCaiDat\CaiDat_PhongTinHocVN.exe"
if exist "%BASE%\BoCaiDat\PhongTinHocVN.exe" del /f /q "%BASE%\BoCaiDat\PhongTinHocVN.exe"
if exist "%BASE%\dist" rmdir /s /q "%BASE%\dist"

"%BASE%\.venv\Scripts\python.exe" -m common.updater "%BASE%\BoCaiDat\NTQ Remote.exe" "%BASE%\QuanLyBanQuyen\WebCapKey_Upload\version.json"

echo.
echo ======================================================
echo   THANH CONG!
echo   Chi co DUY NHAT 1 FILE mang di moi phong may:
echo       BoCaiDat\NTQ Remote.exe
echo ======================================================
if "%NO_PAUSE%"=="" pause
exit /b 0

:err
echo.
echo Co loi xay ra trong qua trinh dong goi!
if "%NO_PAUSE%"=="" pause
exit /b 1
