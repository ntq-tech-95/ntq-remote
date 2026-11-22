@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==================================================================
echo   PHAT HANH PHIEN BAN MOI 1 CHAM (HUONG A - CHAY NGAY TREN MAY)
echo   Tu dong: Kiem thu -> Dong goi EXE -> GitHub Release -> Cloudflare
echo ==================================================================
echo.
if exist "BoCaiDat\NTQ Remote.exe" (
    echo [Meo] Neu chi muon day ban 2.0.0 dang co san trong BoCaiDat\ len mang ngay:
    set /p REUSE="Dung lai file NTQ Remote.exe hien co (nhanh hon ~90s)? [y/N]: "
) else (
    set "REUSE=n"
)

if /i "%REUSE%"=="y" (
    ".venv\Scripts\python.exe" -m common.release_publisher --reuse-exe --skip-tests
) else (
    ".venv\Scripts\python.exe" -m common.release_publisher
)

if errorlevel 1 (
    echo.
    echo [LOI] Qua trinh phat hanh gap su co!
    echo (Neu nhap sai Token, co the chay lai voi tham so: --reset-tokens)
)
echo.
pause
