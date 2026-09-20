@echo off
chcp 65001 >nul
title MES 智能制造执行系统启动器

echo ===================================================
echo       智能无线充 MES 制造执行系统 启动中...
echo ===================================================
echo.
echo 正在启动数据库服务 (6060 端口)...
start "MES-数据库服务(6060)" cmd /k "python backend/db_server.py"

timeout /t 2 /nobreak >nul

echo 正在启动后端数据接口服务 (8080 端口)...
start "MES-后端接口服务(8080)" cmd /k "python backend/api_server.py"

timeout /t 2 /nobreak >nul

echo 正在启动前端静态页面服务 (6021 端口)...
start "MES-前端静态服务(6021)" cmd /k "python backend/static_server.py"

timeout /t 2 /nobreak >nul

echo.
echo ===================================================
echo  服务启动完成！
echo  前端页面访问：http://127.0.0.1:6021
echo  后端接口地址：http://127.0.0.1:8080
echo  数据库服务地址：http://127.0.0.1:6060
echo  默认管理员账号：admin  密码：123456
echo ===================================================
echo.
echo 正在自动为您打开浏览器...
start http://127.0.0.1:6021

pause
