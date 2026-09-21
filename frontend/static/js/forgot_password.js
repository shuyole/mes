initParticles();

const captchaImg = document.getElementById("captcha-img");
function refreshCaptcha() {
    captchaImg.src = API_BASE + "/api/captcha?t=" + Date.now();
}
if (captchaImg) {
    captchaImg.onclick = refreshCaptcha;
    refreshCaptcha();
}

const form = document.getElementById("fpForm");
const errorBox = document.getElementById("fpError");
const okBox = document.getElementById("fpOk");

if (form) {
    form.onsubmit = async function (e) {
        e.preventDefault();
        errorBox.style.display = "none";
        okBox.style.display = "none";

        let username = form.username.value;
        let student_id = form.student_id.value;
        let new_password = form.new_password.value;
        let confirm = form.confirm.value;
        let captcha = form.captcha.value;

        if (new_password !== confirm) {
            errorBox.textContent = "两次输入的新密码不一致";
            errorBox.style.display = "block";
            return;
        }

        let res = await apiPost("/api/forgot_password", {
            username,
            student_id,
            new_password,
            confirm,
            captcha
        });

        if (res.ok) {
            okBox.textContent = "密码重置成功！正在跳转到登录页...";
            okBox.style.display = "block";
            setTimeout(function () {
                window.location.href = "/login";
            }, 1000);
        } else {
            errorBox.textContent = res.error || "重置失败";
            errorBox.style.display = "block";
            refreshCaptcha();
        }
    };
}
