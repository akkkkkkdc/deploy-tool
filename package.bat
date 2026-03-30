@echo off
echo ===== 安装依赖 =====
pip install -r requirements.txt

echo ===== 打包exe =====
pyinstaller --noconfirm --onefile --windowed --name "Jar包一键部署工具" ^
    --add-data "data;data" ^
    --hidden-import=paramiko.paramiko ^
    --hidden-import=cryptography.fernet ^
    --hidden-import=PyQt6 ^
    main.py

echo ===== 完成 =====
echo exe文件在 dist 目录下
pause
