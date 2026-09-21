// 检查本地是否有已登录的用户信息
let userStr = localStorage.getItem("user");
if (!userStr) {
    // 未登录则跳转到登录页
    window.location.href = "/login";
}
let currentUser = JSON.parse(userStr || "{}");

// 时钟刷新
function updateClock() {
    let el = document.getElementById("clock");
    if (el) el.textContent = new Date().toTimeString().split(" ")[0];
}
setInterval(updateClock, 1000);
updateClock();

// 将用户信息展示在页面上
function renderUser() {
    let name = currentUser.display_name || currentUser.username;
    if (document.getElementById("userName")) document.getElementById("userName").textContent = name;
    if (document.getElementById("roleChip")) document.getElementById("roleChip").textContent = currentUser.role_label;

    if (document.getElementById("statAccount")) document.getElementById("statAccount").textContent = currentUser.username;
    if (document.getElementById("statRole")) document.getElementById("statRole").textContent = currentUser.role_label;
    if (document.getElementById("statStatus")) document.getElementById("statStatus").textContent = "启用";
    if (document.getElementById("statLoginStatus")) document.getElementById("statLoginStatus").textContent = "有效在线";

    if (document.getElementById("infoUsername")) document.getElementById("infoUsername").textContent = currentUser.username;
    if (document.getElementById("infoDisplayName")) document.getElementById("infoDisplayName").textContent = name;
    if (document.getElementById("infoRole")) document.getElementById("infoRole").textContent = currentUser.role_label;

    if (document.getElementById("currentAccount")) document.getElementById("currentAccount").textContent = currentUser.username;
    if (document.getElementById("currentRoleLabel")) document.getElementById("currentRoleLabel").textContent = currentUser.role_label;
}
renderUser();

// 退出登录
let logoutBtn = document.getElementById("logoutLink");
if (logoutBtn) {
    logoutBtn.onclick = function () {
        localStorage.removeItem("user");
        window.location.href = "/login";
    };
}
