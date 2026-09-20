/* station_st01.js —— ST01 自动上料专用监控页脚本 */
(function () {
    "use strict";

    let timer = null;

    function initStationST01Page() {
        var $heroTag   = document.getElementById("heroStatusTag");
        var $plcDot    = document.getElementById("plcDot");
        var $plcText   = document.getElementById("plcStatusText");
        var $plcIp     = document.getElementById("plcIp");
        var $plcPort   = document.getElementById("plcPort");
        var $plcBase   = document.getElementById("plcBase");
        var $plcLast   = document.getElementById("plcLast");
        var $plcErr    = document.getElementById("plcErr");
        var $statusBig = document.getElementById("statusBig");
        var $orderNo   = document.getElementById("orderNo");
        var $processed = document.getElementById("processedQty");
        var $cycle     = document.getElementById("cycleSec");
        var $lineRun   = document.getElementById("lineRun");
        var $lineAlarm = document.getElementById("lineAlarm");
        var $sensors   = document.getElementById("sensorsWrap");
        var $regs      = document.getElementById("regsWrap");
        var $params    = document.getElementById("paramsWrap");
        var $desc      = document.getElementById("descText");
        var $qc        = document.getElementById("qcText");

        function clsStatus(s) {
            if (s === "运行") return "run";
            if (s === "故障") return "err";
            if (s === "空闲") return "idle";
            return "off";
        }

        function render(data) {
            if (!data.ok) {
                if ($heroTag) {
                    $heroTag.textContent = "加载失败";
                    $heroTag.className = "st01-hero-tag tag-err";
                }
                return;
            }
            var st = data.status || "空闲";

            if ($heroTag) {
                $heroTag.textContent = st + " · " + (data.plc.connected ? "PLC 在线" : "PLC 离线");
                $heroTag.className = "st01-hero-tag " +
                    (data.plc.connected ? (st === "运行" ? "tag-run" : "tag-idle") : "tag-off");
            }

            if ($plcIp) $plcIp.textContent = data.plc.ip || "--";
            if ($plcPort) $plcPort.textContent = data.plc.port || "--";
            if ($plcBase) $plcBase.textContent = "HR" + (data.station.plc_address || 10);
            if ($plcDot && $plcText && $plcErr) {
                if (data.plc.connected) {
                    $plcDot.classList.add("on");
                    $plcText.textContent = "PLC 在线 · Modbus TCP 已建立";
                    $plcText.style.color = "#34d399";
                    $plcErr.textContent = "--";
                } else {
                    $plcDot.classList.remove("on");
                    $plcText.textContent = "PLC 离线 · " + (data.plc.error_msg || "未连接");
                    $plcText.style.color = "#f87171";
                    $plcErr.textContent = data.plc.error_msg || "未连接";
                }
            }
            if ($plcLast) $plcLast.textContent = data.plc.last_read_time || "--";

            if ($statusBig) {
                $statusBig.textContent = st;
                $statusBig.className = "status-big-value " + clsStatus(st);
            }
            if ($orderNo) $orderNo.textContent = data.line.order_no || "--";
            if ($processed) $processed.textContent = data.processed_qty || 0;
            if ($cycle) $cycle.textContent = (data.station.cycle_sec || 3) + " s/件";
            if ($lineRun) $lineRun.textContent = data.line.running ? "运行中" : "待机";
            if ($lineAlarm) {
                $lineAlarm.textContent = data.line.alarm ? "故障报警" : "正常";
                $lineAlarm.style.color = data.line.alarm ? "#f87171" : "#34d399";
            }

            var sensors = data.sensors || [];
            if ($sensors) {
                if (!sensors.length) {
                    $sensors.innerHTML = '<div class="st01-loading">该工位暂未配置传感器</div>';
                } else {
                    $sensors.innerHTML = sensors.map(function (s) {
                        var on = s.status === "ON";
                        return '<div class="sensor-row ' + (on ? "on" : "off") + '">' +
                            "<div><div class=\"sensor-name\">" + s.name + "</div>" +
                            '<div class="sensor-pin">' + s.pin + "</div></div>" +
                            '<span class="sensor-led ' + (on ? "on" : "off") + '">' +
                            (on ? "联通" : "断开") + "</span>" +
                        "</div>";
                    }).join("");
                }
            }

            var regs = data.registers || {};
            if ($regs) {
                $regs.innerHTML = Object.keys(regs).map(function (k) {
                    var v = regs[k];
                    var noData = v === "--" || v === null || v === undefined;
                    return '<div class="reg-cell">' +
                        '<div class="reg-addr">' + k + "</div>" +
                        '<div class="reg-val ' + (noData ? "no-data" : "") + '">' + (noData ? "--" : v) + "</div>" +
                    "</div>";
                }).join("");
            }

            var params = data.params || [];
            if ($params) {
                if (!params.length) {
                    $params.innerHTML = '<div class="st01-loading">该工位暂未配置工艺参数</div>';
                } else {
                    $params.innerHTML = params.map(function (p) {
                        return '<div class="param-row">' +
                            '<span class="param-key">' + p.key + "</span>" +
                            '<span class="param-val">' + p.value + "</span>" +
                            '<span class="param-std">' + (p.standard || "") + "</span>" +
                        "</div>";
                    }).join("");
                }
            }

            if ($desc) $desc.textContent = data.station.desc || "--";
            if ($qc) $qc.textContent = data.qc_criteria || "--";
        }

        function poll() {
            apiGet("/api/station_st01")
                .then(render)
                .catch(function () { /* 静默失败 */ });
        }

        poll();
        timer = setInterval(poll, 2000);

        return () => {
            if (timer) clearInterval(timer);
        };
    }

    if (window.registerPage) {
        window.registerPage('station_st01', initStationST01Page);
    }
})();
