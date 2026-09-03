@echo off
rem ============================================================
rem  Build GitBundleBackuper.exe with PyInstaller
rem  Double-click or run in terminal.
rem  Output: dist\GitBundleBackuper.exe
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

rem ---- locate python ----
set "PY="
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 ( set "PY=py -3" ) else (
        echo [ERROR] Python not found. Install Python 3 first.
        pause
        exit /b 1
    )
)

echo [1/3] Installing build dependencies ...
%PY% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )

echo [2/3] Building exe ...
rem 先生成最新图标（高清 PNG + 多尺寸 ICO）
%PY% test\make_icon.py
if errorlevel 1 ( echo [WARN] make_icon.py 执行失败，将使用现有图标继续 )

%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name GitBundleBackuper ^
    --icon "GitBundleBackuper.ico" ^
    --version-file "version_info.txt" ^
    --collect-all customtkinter ^
    --collect-all PIL ^
    --add-data "themes\lavender.json;themes" ^
    --add-data "GitBundleBackuper.ico;." ^
    --add-data "icon.png;." ^
    main.py
if errorlevel 1 ( echo [ERROR] PyInstaller failed & pause & exit /b 1 )

echo [3/3] Done.
echo.
echo Output exe: %cd%\dist\GitBundleBackuper.exe
echo Note: put the exe next to a ".git" folder to auto-select it on start.
pause
