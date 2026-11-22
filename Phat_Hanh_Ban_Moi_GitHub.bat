@echo off
chcp 65001 > nul
cd /d "%~dp0"
setlocal EnableDelayedExpansion

echo ==============================================================
echo   PHAT HANH PHIEN BAN MOI TU DONG LEN GITHUB (CI/CD)
echo   (GitHub tu build EXE + tao Release + cap nhat phongtin-key)
echo ==============================================================
echo.

if not exist ".git" (
    echo [LOI] Thu muc nay chua ket noi GitHub!
    echo Hay xem huong dan thiet lap 1 lan trong file:
    echo     Huong_Dan_Tu_Dong_Phat_Hanh.txt
    pause
    exit /b 1
)

set /p VER="Nhap so phien ban moi (VD 2.1.0): "
if "%VER%"=="" (
    echo Da huy vi chua nhap so phien ban.
    pause
    exit /b 1
)
set "VER=%VER:v=%"
set "VER=%VER:V=%"
set /p NOTES="Ghi chu thay doi (nhan Enter de bo qua): "
if "%NOTES%"=="" set "NOTES=Cap nhat NTQ Remote v%VER%"

echo.
echo [1/4] Dang dong bo so phien ban %VER% vao ma nguon...
".venv\Scripts\python.exe" -m common.updater --bump "%VER%"
if errorlevel 1 (
    echo [LOI] So phien ban khong hop le. Hay nhap dang X.Y.Z ^(VD 2.1.0^).
    pause
    exit /b 1
)

echo [2/4] Kiem tra an toan (dam bao khong day private_key.pem)...
git status --short

echo [3/4] Dang commit ma nguon va tao tag v%VER%...
git add -A
git commit -m "Phat hanh NTQ Remote v%VER%: %NOTES%"
git tag -f "v%VER%"

echo [4/4] Dang day len GitHub (se tu dong build & phat hanh)...
git push origin HEAD
if errorlevel 1 (
    echo [LOI] Khong day duoc len GitHub. Kiem tra mang hoac dang nhap Git.
    pause
    exit /b 1
)
git push origin "v%VER%" --force
if errorlevel 1 (
    echo [LOI] Khong day duoc tag v%VER% len GitHub.
    pause
    exit /b 1
)

echo.
echo ==============================================================
echo   DA DAY TAG v%VER% LEN GITHUB THANH CONG!
echo   Vao tab "Actions" tren GitHub cua ban de xem qua trinh:
echo   1. Tu dong chay kiem thu va build NTQ-Remote.exe
echo   2. Tu dong tao GitHub Release v%VER%
echo   3. Tu dong cap nhat https://phongtin-key.pages.dev/version.json
echo ==============================================================
pause
