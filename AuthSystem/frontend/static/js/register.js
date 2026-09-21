initParticles();

const form = document.getElementById("registerForm");
const errorBox = document.getElementById("registerError");
const okBox = document.getElementById("registerOk");

if (form) {
    form.onsubmit = async function (e) {
        e.preventDefault();
        errorBox.style.display = "none";
        okBox.style.display = "none";

        let username = form.username.value;
        let display_name = form.display_name.value;
        let student_id = form.student_id.value;
        let password = form.password.value;
        let confirm = form.confirm.value;

        if (password !== confirm) {
            errorBox.textContent = "两次输入的密码不一致";
            errorBox.style.display = "block";
            return;
        }

        let res = await apiPost("/api/register", {
            username,
            display_name,
            student_id,
            password,
            confirm
        });

        if (res.ok) {
            okBox.textContent = "注册成功！正在跳转到登录页...";
            okBox.style.display = "block";
            setTimeout(function () {
                window.location.href = "/login";
            }, 1000);
        } else {
            errorBox.textContent = res.error || "注册失败";
            errorBox.style.display = "block";
        }
    };
}
