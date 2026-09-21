function initParticles() {
    let canvas = document.getElementById("particles-bg");
    if (!canvas) return;

    let ctx = canvas.getContext("2d");
    let w = canvas.width = window.innerWidth;
    let h = canvas.height = window.innerHeight;

    window.onresize = function () {
        w = canvas.width = window.innerWidth;
        h = canvas.height = window.innerHeight;
    };

    let list = [];
    for (let i = 0; i < 45; i++) {
        list.push({
            x: Math.random() * w,
            y: Math.random() * h,
            vx: (Math.random() - 0.5) * 0.4,
            vy: (Math.random() - 0.5) * 0.4,
            r: Math.random() * 1.5 + 0.8
        });
    }

    function render() {
        ctx.clearRect(0, 0, w, h);
        for (let i = 0; i < list.length; i++) {
            let p = list[i];
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 0 || p.x > w) p.vx = -p.vx;
            if (p.y < 0 || p.y > h) p.vy = -p.vy;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
            ctx.fillStyle = "rgba(34, 211, 238, 0.6)";
            ctx.fill();

            for (let j = i + 1; j < list.length; j++) {
                let p2 = list[j];
                let dist = Math.hypot(p.x - p2.x, p.y - p2.y);
                if (dist < 110) {
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.strokeStyle = "rgba(34, 211, 238, " + (1 - dist / 110) * 0.12 + ")";
                    ctx.stroke();
                }
            }
        }
        requestAnimationFrame(render);
    }
    render();
}
