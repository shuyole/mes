@echo off
chcp 65001 >nul
title 用户认证系统启动器

echo ===================================================
echo    用户认证系统（登录 / 注册 / 找回密码 / 修改密码）
echo             三端服务架构启动中...
echo ===================================================
echo.
echo 正在启动数据库服务 (6070 端口)...
start "认证-数据库服务(6070)" cmd /k "python backend/db_server.py"

timeout /t 2 /nobreak >nul

echo 正在启动后端接口服务 (8090 端口)...
start "认证-后端接口服务(8090)" cmd /k "python backend/api_server.py"

timeout /t 2 /nobreak >nul

echo 正在启动前端静态页面服务 (6031 端口)...
start "认证-前端静态服务(6031)" cmd /k "python backend/static_server.py"

timeout /t 2 /nobreak >nul

echo.
echo ===================================================
echo  服务启动完成！
echo  前端页面访问：http://127.0.0.1:6031
echo  后端接口地址：http://127.0.0.1:8090
echo  数据库服务地址：http://127.0.0.1:6070
echo  内置管理员账号：admin   密码：admin123
echo ===================================================
echo.
echo 正在自动为您打开浏览器...
start http://127.0.0.1:6031

pause
