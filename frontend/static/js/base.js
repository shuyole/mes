/* base.js —— 全站母版 base.html 专属脚本
   职责：定时轮询 /api/stats，更新顶栏右侧的产线状态药丸（运行/暂停/报警/待机）。
   依赖：app.js 的 fetch 包装器（自动补 API_BASE、带 Cookie、401 跳登录），必须在其后加载。 */
(function () {
    "use strict";

    function updateTopbarStatus() {
        // 公开页面（登录 / 注册 / 找回密码）不轮询：顶栏状态区在这些页面不显示，
        // 且未登录时轮询必然 401，会被会话处理逻辑顶回登录页
        if (isPublicPage()) return;
        fetch("/api/stats").then(function (r) { return r.json(); }).then(function (data) {
            var linePill = document.getElementById("topbarLineStatus");
            var lineText = document.getElementById("topbarLineText");
            if (!linePill || !lineText) return;

            var line = data.line || {};
            if (line.alarm) {
                linePill.className = "live-status-pill alarm";
                lineText.textContent = "异常急停: " + (line.alarm_msg || "报警");
            } else if (line.running) {
                linePill.className = "live-status-pill running";
                lineText.textContent = "生产中 (" + (line.order_no || "在制") + ") · " +
                    (line.completed_qty || 0) + "/" + (line.quantity || 0);
            } else {
                linePill.className = "live-status-pill idle";
                lineText.textContent = line.order_no ? "产线暂停" : "产线待机中";
            }
        }).catch(function () { /* 后端短暂不可达时保留上次文案，不打扰用户 */ });
    }

    updateTopbarStatus();
    setInterval(updateTopbarStatus, 3000);
})();
