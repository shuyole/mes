// 必填字段提示：用输入框上的 data-hint 文案代替浏览器默认提示
// 顶层立即执行逻辑：遍历页面上所有带 required 属性的输入项，逐个接管其校验失败时的提示文案
document.querySelectorAll("[required]").forEach(el => {
    // 浏览器判定校验不通过时触发 invalid：按失败原因设置自定义提示；
    // 有 data-hint 就优先用表单自带的文案，没有则用兜底文案
    el.addEventListener("invalid", () => {
        // 空值 -> 必填提示
        if (!el.value.trim()) {
            el.setCustomValidity(el.dataset.hint || "请填写此字段");
        } else if (el.validity.tooShort) {
            // 有值但长度不满足 minlength -> 过短提示
            el.setCustomValidity(el.dataset.hint || "内容过短");
        } else {
            // 其它校验失败原因不做自定义文案，交回浏览器默认提示
            el.setCustomValidity("");
        }
    });
    // 用户重新输入时立刻清除自定义提示，让浏览器重新走一轮校验，避免旧错误一直挂着
    el.addEventListener("input", () => el.setCustomValidity(""));
});
