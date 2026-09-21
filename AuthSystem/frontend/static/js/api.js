// api.js - 前端向 8090 后端发送网络请求的函数
const API_BASE = "http://127.0.0.1:8090";

async function apiGet(path) {
    const res = await fetch(API_BASE + path);
    return await res.json();
}

async function apiPost(path, data) {
    const res = await fetch(API_BASE + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data || {})
    });
    return await res.json();
}
