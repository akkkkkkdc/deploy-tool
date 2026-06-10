@echo off
setlocal
set PYTHONIOENCODING=utf-8

REM Build DeployTool.exe via PyInstaller (onedir for fast startup).
REM Strategy: minimal hooks, collect only what main.py imports.

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist DeployTool.spec del /q DeployTool.spec

echo ===== Build (minimal hook, onedir) =====
D:\Softwares\study\python\python.exe -m PyInstaller ^
    --noconfirm ^
    --windowed ^
    --name DeployTool ^
    --add-data "data;data" ^
    --icon "icon.ico" ^
    --hidden-import=paramiko ^
    --hidden-import=cryptography.fernet ^
    --hidden-import=cryptography.hazmat.primitives.kdf.hkdf ^
    --hidden-import=cryptography.hazmat.primitives.kdf.pbkdf2 ^
    --collect-data=PyQt6 ^
    --exclude-module=tkinter ^
    --exclude-module=unittest ^
    --exclude-module=pydoc ^
    --exclude-module=doctest ^
    --exclude-module=test ^
    main.py

if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo ===== Done =====
echo Output: dist\DeployTool\DeployTool.exe
REM === Post-build cleanup: strip unused Qt6 modules ===
echo Cleaning unused Qt6 modules...
D:\Softwares\study\python\python.exe cleanup_qt.py

echo Total size:
dir /s /-c dist\DeployTool | findstr "File(s)"
