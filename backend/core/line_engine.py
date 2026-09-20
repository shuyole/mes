# -*- coding: utf-8 -*-
"""工业装配流水线推进仿真引擎与工位状态机模块。

职责：
1. 维护产线全局状态机（LINE：真实产线，VIRTUAL：虚拟仿真产线）；
2. 管理 ST01~ST06 工位节拍推进、托盘位移、机械臂搬运任务与合格/不良品判定；
3. 后台常驻 line_simulator 守护线程：依据调速倍率每秒推进仿真并同步寄存器；
4. 提供工单下发、完工收尾、手动进度干预与过站履历持久化；
5. 提供 PLC 寄存器到虚拟产线的边沿触发反向控制（apply_plc_register_control）。
"""

from datetime import datetime
from functools import partial
from threading import RLock
import time

from common import (
    LAST_STATION_NAME,
    STATION_COUNT,
    STATION_DEFS,
    _as_int,
    add_log,
    db_cursor,
    get_sim_speed,
    make_line_state,
)
from core.plc import (
    PLC_STATE,
    write_plc_map,
    write_to_plc,
)

# 产线状态互斥锁：line_simulator 后台线程与各 HTTP 请求都会读写全局 LINE，用可重入锁避免读到中间状态
line_lock = RLock()

# 产线运行时状态（后台线程 line_simulator 持续修改，读写都需持有 line_lock）
# LINE：真实产线，只有 PLC 在线时才推进，工位指示灯跟联机状态走
# VIRTUAL：本地虚拟产线，不依赖 PLC，单独页面演示
LINE = make_line_state()
VIRTUAL = make_line_state()
VIRTUAL_LOGS = []
VIRTUAL_RECORDS = []
PLC_REQUIRED_MSG = "PLC 未连接，真实工位不会动作。请先在设备管理连接 PLC，或打开「虚拟产线」演示。"

ORDER_STATUSES = ("待生产", "生产中", "暂停", "返工", "已完成")


def line_run_text(state=None):
    """把当前产线状态格式化成和页面顶栏一样的一句话。调用方需已持有 line_lock。"""
    state = state if state is not None else LINE
    stations = state["stations"]
    station = stations[state["station_index"]] if stations else {}
    return (
        f"当前工单 {state['order_no'] or '空闲'} ｜ {state['product_name'] or '等待下发'} ｜ "
        f"进度 {state['completed_qty']}/{state['quantity'] or 0} ｜ "
        f"节拍 {state['piece_progress']}% ｜ "
        f"{station.get('code', '')} {station.get('name', '')} {station.get('status') or '空闲'}"
    ).strip()


def update_order_progress(order_id, **fields):
    """更新指定工单的若干字段。

    参数 order_id：工单主键；参数 fields：要更新的「列名=新值」，例如 status、progress、completed_qty。
    返回：无。fields 为空时直接返回，不产生 SQL。
    说明：列名来自内部调用方的关键字参数，值仍走占位符绑定，不存在外部输入拼接列名的风险。
    """
    if not fields:
        return
    assignments = ", ".join(f"{key}=%s" for key in fields)
    values = list(fields.values()) + [order_id]
    with db_cursor() as cursor:
        cursor.execute(f"UPDATE production_orders SET {assignments} WHERE id=%s", values)


def _order_view(order):
    """把工单行整理成前端进度控件可用的字典。"""
    quantity = max(_as_int(order.get("quantity")), 0)
    done = min(max(_as_int(order.get("completed_qty")), 0), quantity)
    status = order.get("status") or "待生产"
    stored = order.get("progress")
    if status == "已完成":
        progress = 100
        done = quantity
    elif stored is not None:
        progress = min(max(_as_int(stored), 0), 99 if done < quantity else 100)
    else:
        progress = int(done * 100 / quantity) if quantity else 0
    return {
        "id": order["id"],
        "order_no": order.get("order_no") or "",
        "quantity": quantity,
        "completed_qty": done,
        "ng_qty": _as_int(order.get("ng_qty")),
        "progress": progress,
        "status": status,
        "current_station": order.get("current_station") or "",
    }


def apply_manual_progress(order, completed_qty=None, new_status=None, rework_qty=None, progress=None):
    """教学用手动改进度：写库、必要时暂停当前产线仿真，不自动下发 PLC。"""
    quantity = max(_as_int(order.get("quantity")), 0)
    done = _as_int(order.get("completed_qty"))
    pct = _as_int(order.get("progress"))
    status = order.get("status") or "待生产"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_percent = progress is not None

    if by_percent:
        pct = min(max(_as_int(progress), 0), 100)
        if not quantity:
            done = 0
        elif pct >= 100:
            done = quantity
        else:
            done = min(int(pct * quantity / 100), max(quantity - 1, 0))
    elif completed_qty is not None:
        done = min(max(_as_int(completed_qty), 0), quantity)
        pct = int(round(done * 100 / quantity)) if quantity else 0

    if new_status:
        if new_status not in ORDER_STATUSES:
            raise ValueError("状态无效")
        status = new_status
        if status == "已完成":
            done = quantity
            pct = 100
        elif status == "待生产" and quantity and done >= quantity:
            done = 0
            pct = 0
        elif status == "返工":
            pull = _as_int(rework_qty) if rework_qty is not None else 1
            pull = min(max(pull, 1), quantity or 1)
            if done >= quantity:
                done = max(quantity - pull, 0)
            pct = int(round(done * 100 / quantity)) if quantity else 0
        elif status == "生产中" and quantity and done >= quantity:
            done = max(quantity - 1, 0)
            pct = int(round(done * 100 / quantity)) if quantity else 0
    elif by_percent:
        if pct >= 100:
            status = "已完成"
        elif status == "已完成" and pct < 100:
            status = "返工"
        elif done > 0 and status == "待生产":
            status = "生产中"
    elif quantity and done >= quantity:
        status = "已完成"
        pct = 100
    elif status == "已完成" and done < quantity:
        status = "返工"
    elif done <= 0 and status == "已完成":
        status = "待生产"
        pct = 0
    elif done > 0 and status == "待生产":
        status = "生产中"

    if status == "已完成":
        done = quantity
        pct = 100
    elif pct >= 100 and done < quantity:
        pct = 99

    station_name = ""
    if done > 0 and quantity:
        idx = min(STATION_COUNT - 1, int((done - 1) * STATION_COUNT / quantity))
        station_name = STATION_DEFS[idx]["name"]
    elif status in ("生产中", "返工"):
        station_name = STATION_DEFS[0]["name"]

    fields = {
        "completed_qty": done,
        "progress": pct,
        "status": status,
        "current_station": LAST_STATION_NAME if status == "已完成" else station_name,
    }
    if status == "已完成":
        fields["finished_at"] = now
        fields["progress"] = 100
        fields["completed_qty"] = quantity
        done = quantity
    else:
        fields["finished_at"] = None
        if status in ("生产中", "返工") and not order.get("started_at"):
            fields["started_at"] = now

    order_id = order["id"]
    finish_line = False
    with line_lock:
        if LINE["order_id"] == order_id:
            LINE["completed_qty"] = done
            LINE["running"] = False
            if status == "已完成":
                finish_line = True
    if finish_line:
        finish_current_order(expected_id=order_id)
    else:
        update_order_progress(order_id, **fields)

    with db_cursor(True) as cursor:
        cursor.execute("SELECT * FROM production_orders WHERE id=%s", (order_id,))
        saved = cursor.fetchone() or {**order, **fields}
    return _order_view(saved)


def _copy_line(state):
    """把一条产线状态复制成可返回给前端的字典。调用方需已持有 line_lock。"""
    return {
        "running": state["running"],
        "alarm": state["alarm"],
        "alarm_msg": state["alarm_msg"],
        "order_id": state["order_id"],
        "order_no": state["order_no"],
        "product_name": state["product_name"],
        "quantity": state["quantity"],
        "completed_qty": state["completed_qty"],
        "ng_qty": state["ng_qty"],
        "station_index": state["station_index"],
        "piece_progress": state["piece_progress"],
        "stations": [dict(item) for item in state["stations"]],
        "robot": dict(state["robot"]),
        "last_update": state["last_update"],
        "progress": int((state["completed_qty"] + state["ng_qty"]) * 100 / max(state["quantity"], 1)) if state["quantity"] else 0,
    }


def _freeze_offline(data):
    """PLC 未连接时工位全部显示离线，指示灯不再闪烁。"""
    data["running"] = False
    data["piece_progress"] = 0
    data["robot"] = {"status": "离线", "position": "--", "task": "等待 PLC 连接", "busy": False}
    data["stations"] = [
        {**item, "status": "离线"} for item in data["stations"]
    ]
    data["plc_connected"] = False
    return data


def snapshot_line(state=None, plc_gate=False):
    """获取产线状态的快照副本，供模板渲染与 /api/ 接口返回。

    参数 plc_gate：True 时未连接 PLC 就把工位冻结为离线（真实在制追踪 / HMI）。
    """
    state = state if state is not None else LINE
    with line_lock:
        data = _copy_line(state)
    data["plc_connected"] = bool(PLC_STATE["connected"])
    data["mode"] = "virtual" if state is VIRTUAL else "real"
    if plc_gate and not data["plc_connected"]:
        return _freeze_offline(data)
    return data


def snapshot_virtual():
    """虚拟产线快照，附带内存中的演示日志与过站记录。"""
    data = snapshot_line(VIRTUAL, plc_gate=False)
    data["plc_connected"] = True
    data["mode"] = "virtual"
    data["logs"] = list(VIRTUAL_LOGS[:20])
    data["records"] = list(VIRTUAL_RECORDS[:30])
    return data


def reset_stations(keep_qty=False, state=None):
    """把各工位与机器人恢复到初始状态。

    参数 keep_qty：True 时保留各工位已加工数量（换工单或复位时累计量继续沿用），False 时清零。
    返回：无。副作用：修改指定产线状态的 stations、robot、station_index、piece_progress，
    并清除报警标志与报警信息（因此复位操作即等于排除故障）。调用方需自行持有 line_lock。
    """
    state = state if state is not None else LINE
    for station in state["stations"]:
        station["status"] = "空闲"
        station["current_order_no"] = ""
        if not keep_qty:
            station["processed_qty"] = 0
    state["robot"] = {"status": "待机", "position": "HOME", "task": "等待指令", "busy": False}
    state["station_index"] = 0
    state["piece_progress"] = 0
    state["alarm"] = False
    state["alarm_msg"] = ""


def _remember_virtual(kind, payload):
    """把虚拟产线的日志/过站记录记在内存里，不写数据库、不写 PLC。"""
    bucket = VIRTUAL_LOGS if kind == "log" else VIRTUAL_RECORDS
    bucket.insert(0, payload)
    del bucket[40:]


def start_line_order(order, state=None, write_plc=True):
    """把一个工单下发到产线并启动仿真。

    参数 order：production_orders 表的一行（需含 id、order_no、product_name、quantity，可选 completed_qty、ng_qty）。
    参数 write_plc：真实产线才写 PLC；虚拟产线只改内存。
    返回：(True, "已下发") 表示启动成功；产线正在执行其它工单或 PLC 未连接时返回失败原因。
    """
    state = state if state is not None else LINE
    if write_plc and not PLC_STATE["connected"]:
        return False, PLC_REQUIRED_MSG
    with line_lock:
        if state["running"] and state["order_id"] and state["order_id"] != order["id"]:
            return False, "产线正在执行其他工单"
        state["running"] = True
        state["alarm"] = False
        state["alarm_msg"] = ""
        state["order_id"] = order["id"]
        state["order_no"] = order["order_no"]
        state["product_name"] = order["product_name"]
        state["quantity"] = order["quantity"]
        state["completed_qty"] = order.get("completed_qty") or 0
        state["ng_qty"] = order.get("ng_qty") or 0
        state["station_index"] = 0
        state["piece_progress"] = 0
        reset_stations(keep_qty=True, state=state)
        state["stations"][0]["status"] = "运行"
        state["stations"][0]["current_order_no"] = order["order_no"]
        state["robot"] = {"status": "运行", "position": "ST01", "task": "上料搬运", "busy": True}
        state["last_update"] = datetime.now().strftime("%H:%M:%S")
        completed_qty = state["completed_qty"]
        run_text = line_run_text(state)
        order_no = state["order_no"]
    if write_plc:
        write_plc_map({0: 1, 1: 1, 2: completed_qty, 6: 1})
        add_log(run_text, order_no, "INFO", "line")
    else:
        _remember_virtual("log", {
            "created_at": datetime.now().strftime("%H:%M:%S"),
            "level": "INFO",
            "message": run_text,
        })
    return True, "已下发"


def _finish_line_state(state=None):
    """把内存里的产线状态收尾成「本工单完成」。调用方必须已持有 line_lock。

    返回：需要回写数据库/PLC 的快照字典；没有在制工单时返回 None。
    """
    state = state if state is not None else LINE
    payload = {
        "order_id": state["order_id"],
        "order_no": state["order_no"],
        "completed_qty": state["completed_qty"],
        "ng_qty": state["ng_qty"],
    }
    state["running"] = False
    state["robot"] = {"status": "待机", "position": "HOME", "task": "本工单完成", "busy": False}
    for station in state["stations"]:
        station["status"] = "完成" if station["processed_qty"] else "空闲"
    payload["run_text"] = line_run_text(state)
    return payload if payload["order_id"] else None


def _persist_finish(payload):
    """把工单完成结果写回数据库、日志和 PLC。不要在持有 line_lock 时调用。"""
    if payload.get("order_id") and payload["order_id"] > 0:
        update_order_progress(
            payload["order_id"],
            status="已完成",
            progress=100,
            completed_qty=payload["completed_qty"],
            ng_qty=payload["ng_qty"],
            current_station=LAST_STATION_NAME,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    add_log(payload.get("run_text") or (
        f"工单 {payload['order_no']} 完成，合格 {payload['completed_qty']}，不良 {payload['ng_qty']}"
    ), payload["order_no"], "INFO", "line")
    write_plc_map({0: 2, 1: STATION_COUNT, 2: payload["completed_qty"], 4: payload["completed_qty"], 5: payload["ng_qty"], 6: 0})


def finish_current_order(expected_id=None):
    """当前工单完成时的收尾处理：停线、回写工单状态、刷新 PLC 与日志。

    参数 expected_id：若给定，仅当产线上正是这个工单时才收尾，避免误完成别的单。
    返回：无。副作用：修改全局 LINE、更新 production_orders、写 PLC 寄存器、写生产日志。
    说明：内部自行加锁；数据库和 PLC 写入都在锁外执行，避免卡住页面轮询。
    """
    with line_lock:
        if expected_id is not None and LINE["order_id"] != expected_id:
            return
        payload = _finish_line_state(LINE)
    if payload:
        _persist_finish(payload)


def record_station_pass(station, ok=True, order_id=None, order_no=None):
    """记录一次工位过站结果，写入 work_records 表。

    参数 station：工位字典（取其中的 code 与 name）；参数 ok：True 记 1 个合格，False 记 1 个不良。
    参数 order_id / order_no：调用方在持锁时拍下的工单快照；缺省时回退读取全局 LINE。
    返回：无。副作用：写数据库；当没有在制工单时直接跳过，避免产生无主记录。
    """
    if order_id is None:
        order_id = LINE["order_id"]
        order_no = LINE["order_no"]
    if not order_id:
        return
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO work_records (order_id, order_no, station_code, station_name, ok_qty, ng_qty, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                order_id,
                order_no,
                station["code"],
                station["name"],
                1 if ok else 0,
                0 if ok else 1,
                "合格" if ok else "不良",
            ),
        )


def _run_jobs(jobs):
    """依次执行仿真节拍里推迟到锁外的 I/O 任务，单次失败不影响后续任务。"""
    for job in jobs:
        try:
            job()
        except Exception as exc:
            name = getattr(getattr(job, "func", job), "__name__", "task")
            print(f"{name} 失败: {exc}")


def _advance_line_locked(jobs, state, write_plc=True, persist=True):
    """推进一拍产线仿真。调用方必须已持有 line_lock，只把数据库/PLC 操作追加到 jobs。"""
    if not state["running"] or state["alarm"] or not state["order_id"]:
        return
    station = state["stations"][state["station_index"]]
    station["status"] = "运行"
    station["current_order_no"] = state["order_no"]
    state["piece_progress"] = min(100, state["piece_progress"] + int(100 / max(station["cycle_sec"], 1)))
    state["robot"]["busy"] = True
    state["robot"]["status"] = "运行"
    state["robot"]["position"] = station["code"]
    state["robot"]["task"] = f"{station['name']}作业"
    state["last_update"] = datetime.now().strftime("%H:%M:%S")

    if state["piece_progress"] < 100:
        return

    state["piece_progress"] = 0
    station["processed_qty"] += 1
    station["status"] = "完成"
    is_last = state["station_index"] >= len(state["stations"]) - 1
    ng = is_last and ((state["completed_qty"] + state["ng_qty"] + 1) % 17 == 0)
    if persist:
        jobs.append(partial(
            record_station_pass,
            dict(station),
            ok=not ng,
            order_id=state["order_id"],
            order_no=state["order_no"],
        ))
    else:
        _remember_virtual("record", {
            "created_at": datetime.now().strftime("%H:%M:%S"),
            "order_no": state["order_no"],
            "station_name": station["name"],
            "ok_qty": 0 if ng else 1,
            "ng_qty": 1 if ng else 0,
            "status": "不良" if ng else "合格",
        })

    if not is_last:
        state["station_index"] += 1
        nxt = state["stations"][state["station_index"]]
        nxt["status"] = "运行"
        nxt["current_order_no"] = state["order_no"]
        state["robot"]["position"] = nxt["code"]
        state["robot"]["task"] = f"转运至{nxt['name']}"
        if write_plc:
            jobs.append(partial(write_to_plc, state["station_index"] + 1, address=1))
        run_text = line_run_text(state)
        if persist:
            jobs.append(partial(add_log, run_text, state["order_no"], "INFO", "line"))
        else:
            _remember_virtual("log", {
                "created_at": datetime.now().strftime("%H:%M:%S"),
                "level": "INFO",
                "message": run_text,
            })
        return

    order_id = state["order_id"]
    order_no = state["order_no"]
    station_name = station["name"]
    if ng:
        state["ng_qty"] += 1
        level = "WARN"
    else:
        state["completed_qty"] += 1
        level = "INFO"
    completed_qty = state["completed_qty"]
    ng_qty = state["ng_qty"]
    quantity = state["quantity"]
    total_done = completed_qty + ng_qty
    progress = int(total_done * 100 / max(quantity, 1))
    if persist:
        jobs.append(partial(
            update_order_progress,
            order_id,
            completed_qty=completed_qty,
            ng_qty=ng_qty,
            progress=min(progress, 99),
            current_station=station_name,
            status="生产中",
        ))
    if write_plc:
        jobs.append(partial(write_plc_map, {2: completed_qty, 4: completed_qty, 5: ng_qty}))
    state["station_index"] = 0
    reset_stations(keep_qty=True, state=state)
    if total_done >= quantity:
        payload = _finish_line_state(state)
        if payload and persist:
            jobs.append(partial(_persist_finish, payload))
        elif payload and not persist:
            _remember_virtual("log", {
                "created_at": datetime.now().strftime("%H:%M:%S"),
                "level": "INFO",
                "message": payload.get("run_text") or f"虚拟工单 {payload['order_no']} 完成",
            })
    else:
        state["stations"][0]["status"] = "运行"
        state["stations"][0]["current_order_no"] = order_no
        run_text = line_run_text(state)
        if persist:
            jobs.append(partial(add_log, run_text, order_no, level, "line"))
        else:
            _remember_virtual("log", {
                "created_at": datetime.now().strftime("%H:%M:%S"),
                "level": level,
                "message": run_text,
            })


def _mirror_virtual_to_line():
    """把虚拟产线画面镜像到真实产线状态（仅展示字段）。

    PLC 在线但真实产线没有在制工单时，ST01、看板、HMI 等读取 LINE 的页面会显示空闲。
    把 VIRTUAL 的工位/机械臂/产量/告警画面复制过来，让所有页面与虚拟仿真页联动。
    调用方必须已持有 line_lock；不复制 running/order_id，避免真实产线被误推进或写库。
    """
    if LINE["running"] and LINE["order_id"]:
        return
    LINE["station_index"] = VIRTUAL["station_index"]
    LINE["piece_progress"] = VIRTUAL["piece_progress"]
    LINE["order_no"] = VIRTUAL["order_no"]
    LINE["product_name"] = VIRTUAL["product_name"]
    LINE["quantity"] = VIRTUAL["quantity"]
    LINE["completed_qty"] = VIRTUAL["completed_qty"]
    LINE["ng_qty"] = VIRTUAL["ng_qty"]
    LINE["alarm"] = VIRTUAL["alarm"]
    LINE["alarm_msg"] = VIRTUAL["alarm_msg"]
    LINE["robot"] = dict(VIRTUAL["robot"])
    LINE["last_update"] = VIRTUAL["last_update"]
    for ls, vs in zip(LINE["stations"], VIRTUAL["stations"]):
        ls["status"] = vs["status"]
        ls["current_order_no"] = vs["current_order_no"]
        ls["processed_qty"] = vs["processed_qty"]


def line_simulator():
    """产线仿真主循环（后台守护线程，常驻）。

    真实产线仅在 PLC 在线时推进；虚拟产线始终可独立演示。
    PLC 在线时虚拟产线也把状态写入寄存器（虚拟产线↔虚拟 PLC 双向联动），
    并把画面镜像到 LINE 供 ST01/看板/HMI 页面显示。
    支持通过 SIMULATION_SPEED 动态调速（1x/2x/5x/10x）。
    """
    while True:
        speed = get_sim_speed()
        sleep_sec = max(0.06, 0.8 / max(speed, 0.1))
        time.sleep(sleep_sec)
        jobs = []
        with line_lock:
            plc_on = bool(PLC_STATE["connected"])
            if plc_on:
                _advance_line_locked(jobs, LINE, write_plc=True, persist=True)
                # PLC 在线：虚拟产线节拍也写入寄存器，HMI/ST01 能看到实时变化
                _advance_line_locked(jobs, VIRTUAL, write_plc=True, persist=False)
                _mirror_virtual_to_line()
            else:
                _advance_line_locked(jobs, VIRTUAL, write_plc=False, persist=False)
        _run_jobs(jobs)


# 上一次轮询到的 HR0（产线状态字），用于检测边沿；None 表示尚未建立基线
_LAST_HR0 = None


def apply_plc_register_control(registers):
    """把 HR0 的边沿变化翻译成虚拟产线控制指令（PLC → 产线反向通道）。

    HR0 约定：0 停止 / 1 运行 / 3 故障。边沿触发，避免与产线自身写入的 HR0 互相打架：
      0/其他 -> 1：有在制工单则继续运行，没有则自动下发一单虚拟演示工单；
      1 -> 0    ：暂停；
      * -> 3    ：注入故障（急停/互锁）；
      3 -> 0/1  ：故障复位，若为 1 则随后继续运行。
    返回：无。只操作 VIRTUAL（PLC 在线时其画面会镜像到 LINE），不写数据库。
    """
    global _LAST_HR0
    hr0 = registers.get("0")
    if hr0 is None:
        return
    if hr0 == _LAST_HR0:
        return
    prev = _LAST_HR0
    _LAST_HR0 = hr0
    # 首次读到寄存器只建立基线，不动作（虚拟 PLC 初值全 0）
    if prev is None:
        return

    with line_lock:
        if hr0 == 3:
            # 已经是故障态就幂等返回（页面注入故障也会写 HR0=3，避免重复记日志）
            if VIRTUAL["alarm"]:
                return
            VIRTUAL["alarm"] = True
            VIRTUAL["running"] = False
            VIRTUAL["alarm_msg"] = "PLC 下发急停 / 故障字（HR0=3）"
            VIRTUAL["robot"]["status"] = "故障"
            VIRTUAL["robot"]["task"] = "等待复位"
            VIRTUAL["stations"][VIRTUAL["station_index"]]["status"] = "故障"
            _remember_virtual("log", {
                "created_at": datetime.now().strftime("%H:%M:%S"),
                "level": "ALARM",
                "message": "PLC 下发 HR0=3，虚拟产线急停",
            })
            return

        if prev == 3 and hr0 in (0, 1):
            # 故障字撤销：先清故障、复位工位
            VIRTUAL["alarm"] = False
            VIRTUAL["alarm_msg"] = ""
            reset_stations(keep_qty=True, state=VIRTUAL)
            _remember_virtual("log", {
                "created_at": datetime.now().strftime("%H:%M:%S"),
                "level": "INFO",
                "message": "PLC 撤销故障字，虚拟产线已复位",
            })
            if hr0 == 0:
                VIRTUAL["running"] = False
                return

        if hr0 == 0:
            if VIRTUAL["running"]:
                VIRTUAL["running"] = False
                VIRTUAL["robot"]["status"] = "待机"
                VIRTUAL["robot"]["busy"] = False
                VIRTUAL["robot"]["task"] = "PLC 下发暂停（HR0=0）"
                _remember_virtual("log", {
                    "created_at": datetime.now().strftime("%H:%M:%S"),
                    "level": "INFO",
                    "message": "PLC 下发 HR0=0，虚拟产线暂停",
                })
            return

        if hr0 == 1:
            if VIRTUAL["alarm"]:
                return
            if VIRTUAL["running"]:
                return
            if VIRTUAL["order_id"]:
                # 有在制工单：继续运行
                VIRTUAL["running"] = True
                VIRTUAL["robot"]["status"] = "运行"
                VIRTUAL["robot"]["busy"] = True
                _remember_virtual("log", {
                    "created_at": datetime.now().strftime("%H:%M:%S"),
                    "level": "INFO",
                    "message": "PLC 下发 HR0=1，虚拟产线继续运行",
                })
                return
            # 无在制工单：自动下发一单虚拟演示工单
            demo_order = {
                "id": -1,
                "order_no": "VIR-" + datetime.now().strftime("%H%M%S"),
                "product_name": "虚拟演示件",
                "quantity": 3,
                "completed_qty": 0,
                "ng_qty": 0,
            }
    # start_line_order 内部会再取锁，需在锁外调用；write_plc=False 避免与 HR0 写回形成回环
    ok, msg = start_line_order(demo_order, state=VIRTUAL, write_plc=False)
    if ok:
        # 补齐工位/机械臂/产量寄存器，让 HMI 立刻看到运行态
        write_plc_map({1: 1, 2: 0, 6: 1})
        _remember_virtual("log", {
            "created_at": datetime.now().strftime("%H:%M:%S"),
            "level": "INFO",
            "message": "PLC 下发 HR0=1，自动下发虚拟演示工单",
        })
