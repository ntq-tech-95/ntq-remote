@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ==================================================================
echo   PHAT HANH PHIEN BAN MOI 1 CHAM (HUONG A - CHAY NGAY TREN MAY)
echo   Tu dong: Kiem thu -> Dong goi EXE -> GitHub Release -> Cloudflare
echo ==================================================================
echo.
echo   [1] Phat hanh day du (Kiem thu + Dong goi EXE moi + GitHub + Cloudflare)
echo   [2] Nhanh (Dung lai file NTQ Remote.exe hien co + GitHub + Cloudflare)
echo   [3] Chi day lai version.json & web len Cloudflare Pages (5 giay)
echo.
set /p MODE="Chon che do [1/2/3 - mac dinh 1]: "
if "%MODE%"=="" set "MODE=1"

if "%MODE%"=="3" (
    ".venv\Scripts\python.exe" -m common.release_publisher --cf-only
    goto :done
)
if "%MODE%"=="2" (
    ".venv\Scripts\python.exe" -m common.release_publisher --reuse-exe --skip-tests
    goto :done
)
".venv\Scripts\python.exe" -m common.release_publisher

:done
if errorlevel 1 (
    echo.
    echo [LOI] Qua trinh phat hanh gap su co!
)
echo.
pause
