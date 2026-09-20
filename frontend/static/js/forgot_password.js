/* forgot_password.js —— 找回密码页专属脚本 */
(function () {
    "use strict";

    let animId = null;

    function initParticles() {
        const canvas = document.getElementById('particles-bg');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const particles = [];
        const COUNT = 55;
        const MAX_DIST = 150;

        function resize() {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        }
        resize();
        window.addEventListener('resize', resize);

        for (let i = 0; i < COUNT; i++) {
            particles.push({
                x: Math.random() * canvas.width,
                y: Math.random() * canvas.height,
                vx: (Math.random() - 0.5) * 0.35,
                vy: (Math.random() - 0.5) * 0.35,
                r: Math.random() * 1.5 + 0.5
            });
        }

        function tick() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            for (let i = 0; i < particles.length; i++) {
                const p = particles[i];
                p.x += p.vx; p.y += p.vy;
                if (p.x < 0 || p.x > canvas.width) p.vx *= -1;
                if (p.y < 0 || p.y > canvas.height) p.vy *= -1;
                ctx.beginPath();
                ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(34, 211, 238, 0.55)';
                ctx.fill();
            }
            for (let i = 0; i < particles.length; i++) {
                for (let j = i + 1; j < particles.length; j++) {
                    const dx = particles[i].x - particles[j].x;
                    const dy = particles[i].y - particles[j].y;
                    const d = Math.sqrt(dx * dx + dy * dy);
                    if (d < MAX_DIST) {
                        ctx.beginPath();
                        ctx.moveTo(particles[i].x, particles[i].y);
                        ctx.lineTo(particles[j].x, particles[j].y);
                        ctx.strokeStyle = 'rgba(34, 211, 238,' + (1 - d / MAX_DIST) * 0.15 + ')';
                        ctx.lineWidth = 0.5;
                        ctx.stroke();
                    }
                }
            }
            animId = requestAnimationFrame(tick);
        }
        tick();
    }

    function initForgotPasswordPage() {
        initParticles();

        const captchaImg = document.getElementById('captcha-img');
        function refreshCaptcha() {
            if (captchaImg) captchaImg.src = `${API_BASE}/api/captcha?t=${Date.now()}`;
        }
        if (captchaImg) {
            refreshCaptcha();
            captchaImg.addEventListener('click', refreshCaptcha);
        }

        const form = document.getElementById('fpForm');
        const errEl = document.getElementById('fpError');

        if (form) {
            form.onsubmit = async (e) => {
                e.preventDefault();
                if (errEl) errEl.style.display = 'none';

                const username = form.username.value.trim();
                const student_id = form.student_id.value.trim();
                const new_password = form.new_password.value;
                const confirm = form.confirm.value;
                const captcha = form.captcha.value.trim();

                if (new_password !== confirm) {
                    if (errEl) {
                        errEl.textContent = '两次输入的密码不一致';
                        errEl.style.display = '';
                    }
                    return;
                }

                const submitBtn = form.querySelector('.fp-submit');
                if (submitBtn) submitBtn.disabled = true;

                try {
                    const res = await apiPost('/api/forgot_password', {
                        username,
                        student_id,
                        new_password,
                        confirm,
                        captcha
                    });
                    if (res.ok) {
                        if (window.showToast) showToast('密码重置成功，请登录', 'success');
                        window.location.hash = '#/login';
                    } else {
                        if (errEl) {
                            errEl.textContent = res.error || '重置失败';
                            errEl.style.display = '';
                        }
                        refreshCaptcha();
                    }
                } catch (err) {
                    if (errEl) {
                        errEl.textContent = err.message || '网络错误，请稍后重试';
                        errEl.style.display = '';
                    }
                    refreshCaptcha();
                } finally {
                    if (submitBtn) submitBtn.disabled = false;
                }
            };
        }

        return () => {
            if (animId) cancelAnimationFrame(animId);
        };
    }

    if (window.registerPage) {
        window.registerPage('forgot_password', initForgotPasswordPage);
    }
})();
