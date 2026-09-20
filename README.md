# 精简版 MES 移植说明

完整步骤请看 **[使用指南.md](使用指南.md)**。下面是最短操作说明。

把整个项目文件夹拷到其他电脑即可。**不要拷 `.venv`**（虚拟环境跟本机 Python 路径绑定，到新电脑会失效）。

## 需要安装的应用

| 应用 | 是否必须 | 说明 |
|------|----------|------|
| Windows 10/11 | 必须 | 当前启动脚本按 Windows 编写 |
| [Python 3.10 或更高](https://www.python.org/downloads/) | **必须** | 安装时务必勾选 **Add python.exe to PATH** |
| 浏览器（Edge / Chrome） | 必须 | 用来打开 http://127.0.0.1:6021 |
| [MySQL 8](https://dev.mysql.com/downloads/mysql/) | 可选 | 有则用 MySQL（默认账号 `root`，密码 `123456`）；没有则自动用本地 `data\mes.db` |
| 西门子 / 其他 PLC 软件 | 不需要 | 产线可本地仿真；要联真机再配 `config\config.json` 里的 PLC 地址 |

不需要再单独安装 Flask、PyMySQL、pymodbus，这些由 `install.bat` 按 `requirements.txt` 自动安装。

也不需要 Node.js、Java、Redis。

## 新电脑操作顺序

1. 安装 Python 3.10+（勾选 Add to PATH）
2. 拷贝本项目文件夹（不要带 `.venv`）
3. 双击 `install.bat` 安装 Python 包
4. 双击 `start.bat` 启动
5. 用浏览器打开 http://127.0.0.1:6021

PLC / 虚拟下位机不是必须的。若要虚拟 PLC，再双击 `start_plc.bat`（占用 502 端口时可能需要管理员权限）。


## 一键安装依赖

在项目目录双击：

```text
install.bat
```

它会创建 `.venv` 并安装 `requirements.txt` 里的包：

- Flask
- PyMySQL
- pymodbus

也可手动执行：

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 一键启动

双击：

```text
start.bat
```

浏览器打开：http://127.0.0.1:6021

可选：另开一个窗口运行 `start_plc.bat`（虚拟 PLC）。Windows 占用 502 端口可能需要管理员权限。

## 换电脑后怎么改配置

编辑 `config\config.json`：

- `database.type`：`auto`（推荐，有 MySQL 用 MySQL，否则 SQLite）/ `mysql` / `sqlite`
- `database.password`：新电脑的 MySQL 密码
- `frontend_port`：前端页面端口，默认 6021（浏览器访问的就是这个）
- `backend_port`：后端接口端口，默认 8080（页面内部调用，无需直接访问）
- `db_service.host` / `db_service.port`：数据库服务地址，默认 `127.0.0.1:6060`（唯一直接连数据库的进程；接口服务通过它执行 SQL）
- `plc.ip` / `plc.port`：真实 PLC 地址

## 账号数据会不会一起过去

- 用 **MySQL**：需要把原电脑的 `mes_db` 导出后再导入，或让新电脑连同一台 MySQL
- 用 **SQLite**：把原电脑的 `data\mes.db` 一起拷过去

只拷代码、不拷数据库时，新电脑会重新初始化空库。

## 目录说明

```text
Server/
  start.bat          一键启动系统（依次启动 6060 / 8080 / 6021 三个服务并打开浏览器）
  frontend/          前端（纯 HTML + CSS + JS，无服务端模板依赖）
    index.html         系统入口骨架
    Templates/         各业务功能纯 HTML 页面
    static/            样式与脚本
      css/               各页面样式表
      js/                页面交互与 API 调用脚本
  backend/           后端（Python 服务）
    db_server.py       数据库服务（6060 端口，唯一直接连数据库）
    api_server.py      后端接口服务（8080 端口，PLC 与业务逻辑，SQL 转交 6060）
    static_server.py   前端静态托管服务（6021 端口）
    common.py          共享模块：配置 / 会话 / 数据库访问客户端
    virtual_plc.py     虚拟 PLC 仿真
  config/            配置文件
    config.json        数据库 / 端口 / 数据库服务 / PLC 配置
  data/              运行时数据（含 SQLite mes.db）
    .epoch             会话代次文件（各服务共享）
```
