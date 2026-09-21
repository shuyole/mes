let mask = document.getElementById("changePwdMask");
let openBtn = document.getElementById("openChangePwdBtn");
let cancelBtn = document.getElementById("changePwdCancel");
let form = document.getElementById("changePwdForm");
let msg = document.getElementById("changePwdMsg");

let user = JSON.parse(localStorage.getItem("user") || "{}");

if (openBtn) {
    openBtn.onclick = function () {
        mask.classList.add("open");
        form.reset();
        msg.textContent = "";
    };
}

if (cancelBtn) {
    cancelBtn.onclick = function () {
        mask.classList.remove("open");
    };
}

if (form) {
    form.onsubmit = async function (e) {
        e.preventDefault();
        let old_password = form.old_password.value;
        let new_password = form.new_password.value;
        let confirm = form.confirm.value;

        if (new_password !== confirm) {
            msg.textContent = "两次输入的新密码不一致";
            msg.className = "modal-msg error";
            return;
        }

        let res = await apiPost("/api/change_password", {
            username: user.username,
            old_password,
            new_password,
            confirm
        });

        if (res.ok) {
            msg.textContent = "密码修改成功！";
            msg.className = "modal-msg success";
            setTimeout(function () {
                mask.classList.remove("open");
            }, 1200);
        } else {
            msg.textContent = res.error || "修改失败";
            msg.className = "modal-msg error";
        }
    };
}
