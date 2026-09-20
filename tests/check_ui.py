"""Read-only UI smoke checks against the existing MES ports.

Run: python tests/check_ui.py
Requires Playwright and Microsoft Edge. Does not issue PLC commands.
Pages are served by the frontend service (6021); login goes through the backend API service (8080).
"""
import json
import os
import tempfile

from playwright.sync_api import sync_playwright


# 页面服务端口（前端）：接口服务在 8080，登录用它的 /api/login
PAGE_PORT = 6021
API_BASE = "http://127.0.0.1:8080"

ROUTES = ["/", "/orders", "/line", "/virtual", "/recipes", "/production",
          "/alarms", "/settings", "/hmi", "/users"]


def main():
    results = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        for port in (PAGE_PORT,):
            context = browser.new_context()
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            base = f"http://127.0.0.1:{port}"
            response = context.request.post(API_BASE + "/api/login", data={
                "username": os.environ.get("MES_TEST_USER", "admin"),
                "password": os.environ.get("MES_TEST_PASSWORD", "ADMIN"),
            })
            assert response.ok, (port, response.status)
            for width in (1440, 1024, 390):
                page.set_viewport_size({"width": width, "height": 1000})
                for route in ROUTES:
                    response = page.goto(base + route, wait_until="networkidle")
                    assert response.status == 200, (port, route, response.status)
                    assert page.locator("link[href*='console.css']").count() == 1
                    assert page.locator(".app-shell").count() == 1
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth > innerWidth"
                    )
                    results.append([port, width, route, overflow])
                    if route == "/hmi":
                        page.wait_for_selector("#stationLeds .station")
                        assert page.locator("#stationLeds h3").evaluate_all(
                            "els => els.every(el => el.getBoundingClientRect().height < 48)"
                        ), (width, "station heading wrapped too narrowly")
                if width in (1440, 390):
                    for route in ("/hmi", "/recipes", "/"):
                        page.goto(base + route, wait_until="networkidle")
                        name = route.strip("/") or "monitor"
                        page.screenshot(path=os.path.join(
                            tempfile.gettempdir(), f"mes-{name}-{width}.png"
                        ), full_page=True)
            page.goto(base + "/orders", wait_until="networkidle")
            page.locator(".filter-btn[data-filter='待生产']").click()
            assert "active" in page.locator(
                ".filter-btn[data-filter='待生产']"
            ).get_attribute("class")
            page.locator("#searchBox").fill("__UI_NO_MATCH__")
            assert page.locator(".order-row:visible").count() == 0
            page.goto(base + "/line", wait_until="networkidle")
            for tab in ("plc", "robot", "trace", "flow"):
                page.locator(f"[data-tab='{tab}']").click()
                assert page.locator(f"#tab-{tab}").is_visible()
            context.clear_cookies()
            for route in ("/login", "/register"):
                page.goto(base + route, wait_until="networkidle")
                results.append([port, 390, route, page.evaluate(
                    "document.documentElement.scrollWidth > innerWidth"
                )])
            context.close()
        browser.close()
    overflow = [result for result in results if result[-1]]
    print(json.dumps({"checked": len(results), "overflows": overflow,
                      "js_errors": errors}, ensure_ascii=False))
    assert not overflow, overflow
    assert not errors, errors


if __name__ == "__main__":
    main()
