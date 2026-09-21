initParticles();

const captchaImg = document.getElementById("captcha-img");
function refreshCaptcha() {
    captchaImg.src = API_BASE + "/api/captcha?t=" + Date.now();
}
if (captchaImg) {
    captchaImg.onclick = refreshCaptcha;
    refreshCaptcha();
}

const form = document.getElementById("loginForm");
const errorBox = document.getElementById("loginError");

if (form) {
    form.onsubmit = async function (e) {
        e.preventDefault();
        errorBox.style.display = "none";

        let username = form.username.value.trim();
        let password = form.password.value;
        let captcha = form.captcha.value.trim();

        // 前端 JS 基础格式校验
        if (!username) {
            errorBox.textContent = "请输入用户名！";
            errorBox.style.display = "block";
            return;
        }
        if (!password) {
            errorBox.textContent = "请输入密码！";
            errorBox.style.display = "block";
            return;
        }
        if (!captcha) {
            errorBox.textContent = "请输入验证码！";
            errorBox.style.display = "block";
            return;
        }

        let res = await apiPost("/api/login", { username, password, captcha });
        if (res.ok) {
            // 前后端分离：将登录成功的用户信息保存在浏览器本地 localStorage
            localStorage.setItem("user", JSON.stringify(res.user));
            window.location.href = "/home";
        } else {
            errorBox.textContent = res.error || "登录失败";
            errorBox.style.display = "block";
            refreshCaptcha();
        }
    };
}
