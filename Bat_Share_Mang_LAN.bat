@echo off
chcp 65001 > nul
setlocal

:: Tu dong xin quyen Quan tri vien (UAC) neu chua chay bang Administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Dang yeu cau quyen Quan tri vien ^(Run as Administrator^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
title Bat Share Thu Muc Qua Network LAN - NTQ Remote

:menu
cls
echo ==================================================================
echo   BAT CHIA SE THU MUC QUA NETWORK (MY COMPUTER -^> NETWORK)
echo   Ho tro Windows 10 / 11 (Hien ten may Giao vien & tat hoi pass)
echo ==================================================================
echo.
echo   [1] Cai tren MAY GIAO VIEN: Bat Network + Share thu muc (chi doc)
echo   [2] Cai tren MAY HOC SINH: Bat che do nhin thay may trong Network
echo   [3] Tat chia se mot thu muc da share truoc do
echo   [4] Thoat
echo.
set /p CHOICE="Chon muc [1/2/3/4 - mac dinh 1]: "
if "%CHOICE%"=="" set "CHOICE=1"

if "%CHOICE%"=="4" exit /b 0
if "%CHOICE%"=="3" goto :unshare
if "%CHOICE%"=="2" goto :student_net
if "%CHOICE%"=="1" goto :teacher_share
goto :menu

:teacher_share
echo.
set "DEFAULT_DIR=%~dp0BoCaiDat"
if not exist "%DEFAULT_DIR%" set "DEFAULT_DIR=%~dp0"
set /p SHARE_DIR="Nhap duong dan thu muc muon share [Enter = %DEFAULT_DIR%]: "
if "%SHARE_DIR%"=="" set "SHARE_DIR=%DEFAULT_DIR%"
set "SHARE_DIR=%SHARE_DIR:"=%"
if "%SHARE_DIR:~-1%"=="\" set "SHARE_DIR=%SHARE_DIR:~0,-1%"

if not exist "%SHARE_DIR%" (
    echo [LOI] Khong tim thay thu muc: "%SHARE_DIR%"
    pause
    goto :menu
)

for %%F in ("%SHARE_DIR%") do set "DEFAULT_NAME=%%~nxF"
set /p SHARE_NAME="Ten thu muc hien trong Network [Enter = %DEFAULT_NAME%]: "
if "%SHARE_NAME%"=="" set "SHARE_NAME=%DEFAULT_NAME%"

echo.
echo [1/4] Dang chuyen mang LAN sang Private...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -ne 'DomainAuthenticated' } | Set-NetConnectionProfile -NetworkCategory Private -ErrorAction SilentlyContinue"

echo [2/4] Dang bat 4 dich vu phat ten may ra Network ^(FDResPub, fdPHost, SSDPSRV, upnphost^)...
for %%S in (fdPHost FDResPub SSDPSRV upnphost) do (
    sc config %%S start= auto >nul 2>&1
    sc start %%S >nul 2>&1
)

echo [3/4] Dang mo Tuong lua cho Network Discovery ^& File Sharing...
powershell -NoProfile -ExecutionPolicy Bypass -Command "foreach ($g in @('Network Discovery','File and Printer Sharing','@FirewallAPI.dll,-32752','@FirewallAPI.dll,-28502')) { Enable-NetFirewallRule -DisplayGroup $g -ErrorAction SilentlyContinue; Enable-NetFirewallRule -Group $g -ErrorAction SilentlyContinue }"

echo [4/4] Dang tat hoi mat khau ^& chia se thu muc '%SHARE_NAME%' ^(chi doc Everyone^)...
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Lsa" /v everyoneincludesanonymous /t REG_DWORD /d 1 /f >nul 2>&1
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Lsa" /v restrictanonymous /t REG_DWORD /d 0 /f >nul 2>&1
icacls "%SHARE_DIR%" /grant "*S-1-1-0:(OI)(CI)R" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command "$sn=$env:SHARE_NAME; $sp=$env:SHARE_DIR; if (Get-SmbShare -Name $sn -ErrorAction SilentlyContinue) { Remove-SmbShare -Name $sn -Force -Confirm:$false }; New-SmbShare -Name $sn -Path $sp -ReadAccess 'Everyone' | Out-Null; Write-Host ('Da share thanh cong: \\' + $env:COMPUTERNAME + '\' + $sn)"

echo.
echo ==================================================================
echo   HOAN TAT! Tren may Hoc sinh:
echo   - Mo My Computer ^(This PC^) -^> bam Network o cot ben trai
echo   - Nhan F5 neu chua thay ngay -^> chon may "%COMPUTERNAME%"
echo   - Mo thu muc "%SHARE_NAME%"
echo   ^(Meo: Neu van bi hoi User/Pass, thu tat them Firewall hoac
echo    vao Manage advanced sharing settings kiem tra 'Turn off password
echo    protected sharing' va kich hoat Guest neu may dung Windows Home/Lite.^)
echo ==================================================================
echo.
pause
goto :menu

:student_net
echo.
echo [1/3] Dang chuyen mang sang Private...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -ne 'DomainAuthenticated' } | Set-NetConnectionProfile -NetworkCategory Private -ErrorAction SilentlyContinue"

echo [2/3] Dang bat dich vu tim may trong LAN...
for %%S in (fdPHost SSDPSRV) do (
    sc config %%S start= auto >nul 2>&1
    sc start %%S >nul 2>&1
)

echo [3/3] Dang mo Tuong lua Network Discovery...
powershell -NoProfile -ExecutionPolicy Bypass -Command "foreach ($g in @('Network Discovery','@FirewallAPI.dll,-32752')) { Enable-NetFirewallRule -DisplayGroup $g -ErrorAction SilentlyContinue; Enable-NetFirewallRule -Group $g -ErrorAction SilentlyContinue }"

echo.
echo Da bat xong Network Discovery cho May Hoc Sinh! Hay mo This PC -^> Network.
echo.
pause
goto :menu

:unshare
echo.
set /p UN_NAME="Nhap ten Share muon go (Enter = BoCaiDat): "
if "%UN_NAME%"=="" set "UN_NAME=BoCaiDat"
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-SmbShare -Name $env:UN_NAME -ErrorAction SilentlyContinue) { Remove-SmbShare -Name $env:UN_NAME -Force -Confirm:$false; Write-Host 'Da ngung chia se.' } else { Write-Host 'Khong tim thay ten Share nay.' }"
echo.
pause
goto :menu
