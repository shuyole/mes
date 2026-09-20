# -*- coding: utf-8 -*-
"""
虚拟 PLC 从站（模拟 Modbus TCP Server）

用途：本机联调用的模拟 PLC。用 pymodbus 启动一个 Modbus TCP 从站，
给 MES 后端接口服务（端口 8080）读写寄存器，无需真实 PLC 设备即可调试。

监听地址：0.0.0.0:502（Modbus TCP 标准端口，本机与局域网均可连接）

保持寄存器（HR）映射：
    HR0  产线状态   0停止 1运行 2完成 3故障
    HR1  当前工位
    HR2  当前产量
    HR4  合格数     HR5 不良数
    HR6  机械臂状态 0待机 1运行 2故障
"""

from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusSparseDataBlock, ModbusDeviceContext, ModbusServerContext

# 从站数据区：保持寄存器（hr）从地址 0 开始连续 100 个，初值全为 0
# 注意：pymodbus 3.15 禁止 ModbusSequentialDataBlock 用 address=0 构造
# （仅允许 1~65534），因此改用 ModbusSparseDataBlock 的字典形式，从 0 开始。
store = ModbusDeviceContext(
    hr=ModbusSparseDataBlock({i: 0 for i in range(100)})
)
# 包装成服务端上下文；single=True 表示只有单个从站单元，后端无需区分 unit id
context = ModbusServerContext(devices=store, single=True)

# 启动时打印寄存器映射表，便于联调时对照地址含义
print("=" * 56)
print("虚拟 PLC 已启动  |  7 工位产线寄存器映射")
print("  监听地址 : 0.0.0.0:502")
print("  HR0  产线状态  0停止 1运行 2完成 3故障")
print("  HR1  当前工位")
print("  HR2  当前产量")
print("  HR4  合格数   HR5 不良数")
print("  HR6  机械臂状态 0待机 1运行 2故障")
print("=" * 56)

# 启动 Modbus TCP 服务，阻塞式监听 0.0.0.0:502，直至进程退出
StartTcpServer(context=context, address=("0.0.0.0", 502))
