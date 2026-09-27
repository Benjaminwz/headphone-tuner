@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 耳機調音台 安裝
echo.
echo  ===== 耳機調音台 安裝 =====
echo.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython
%PY% -c "import tkinter" >nul 2>nul || goto nopython

echo [1/3] 安裝需要的套件：numpy、sounddevice、pycaw、comtypes、brotli
%PY% -m pip install --disable-pip-version-check -q numpy sounddevice pycaw comtypes brotli
if errorlevel 1 goto pipfail

echo [2/3] 檢查 Equalizer APO（等化器核心）
if exist "%ProgramFiles%\EqualizerAPO\EqualizerAPO.dll" (
  echo       已安裝
) else (
  echo       還沒安裝，幫你打開下載頁面。
  echo       安裝到最後會跳出設定視窗：勾選你的耳機用的輸出裝置，按確定，然後重新開機。
  start "" "https://sourceforge.net/projects/equalizerapo/"
)

echo [3/3] 建立桌面捷徑，打開調音台
%PY% "%~dp0耳機調音台.pyw" --make-shortcut
echo.
echo 完成！之後從桌面的「耳機調音台」打開就可以了。
pause
exit /b 0

:pipfail
echo.
echo 套件安裝失敗：請確認有連上網路，再執行一次這個檔案。
pause
exit /b 1

:nopython
echo 找不到 Python。請先到 python.org 下載安裝，
echo 安裝畫面記得勾選「Add python.exe to PATH」，裝好後再執行一次這個檔案。
start "" "https://www.python.org/downloads/"
pause
exit /b 1
