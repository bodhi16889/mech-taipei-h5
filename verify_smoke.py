"""Smoke test for threejs-mech-taipei/index.html.

Starts a local static server, drives the page in headless Chromium (Playwright),
and asserts the real behaviour: rendering runs, WASD moves the mech, a collision
collapses a building, and the HUD records "扣除 5,000 萬建造費".

Usage:  python verify_smoke.py [--headed] [--port 0]   (0 = 自動選空閒埠)
Exit:   0 = all checks passed, 1 = failure (details printed).
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
COST = 50_000_000


def serve(directory: Path, port: int) -> socketserver.TCPServer:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *a, **k: None  # 靜音

    class Server(socketserver.TCPServer):
        allow_reuse_address = True

    server = Server(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--port", type=int, default=0, help="0 = 自動選一個空閒埠（預設）；也可指定固定埠")
    parser.add_argument("--base-url", default="", help="改測已有網址（GitHub Pages／tunnel／區網 IP），不啟本機 server")
    parser.add_argument("--screenshot", default=str(ARTIFACTS / "smoke-collapse.png"))
    args = parser.parse_args()

    ARTIFACTS.mkdir(exist_ok=True)
    if args.base_url:
        url = args.base_url
        server = None
        print(f"testing existing URL: {url}")
    else:
        server = serve(ROOT, args.port)
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/index.html"
        print(f"serving {ROOT} on http://127.0.0.1:{port}/index.html")
    failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        console_errors: list[str] = []

        def on_console(msg):
            if msg.type != "error":
                return
            # assets/models/*.glb 是選用素材；不存在時程式會 fallback 回方塊版本，
            # 瀏覽器仍會為 404 印出 resource error，故此處視為預期訊息。
            if "assets/models/" in msg.text or "assets/models/" in (msg.location or {}).get("url", ""):
                return
            console_errors.append(msg.text)

        page.on("console", on_console)
        page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

        page.goto(url, wait_until="load")
        page.wait_for_function("window.__game && window.__game.state.ready", timeout=30_000)

        # 1) render loop alive（headless swiftshader 帧率很低且不穩，只看有在前進）
        f0 = page.evaluate("window.__game.frame")
        time.sleep(1.5)
        f1 = page.evaluate("window.__game.frame")
        if not check("render loop advances", f1 - f0 >= 8, f"{f0} -> {f1} frames in 1.5s"):
            failures.append("render loop")

        # 2) scene content: buildings + mech exist
        counts = page.evaluate(
            "({buildings: window.__game.buildings.length, alive: window.__game.aliveBuildings})"
        )
        if not check("city spawned", counts["buildings"] >= 6 and counts["alive"] == counts["buildings"], str(counts)):
            failures.append("city spawn")

        # 3) WASD moves the mech (short press, no collision yet)
        #    先關掉開始遮罩，模擬使用者點擊後的畫面
        page.evaluate("document.getElementById('overlay').classList.add('hidden')")
        time.sleep(0.6)
        page.screenshot(path=str(ARTIFACTS / "smoke-city.png"))
        start = page.evaluate("({x: window.__game.mech.position.x, z: window.__game.mech.position.z})")
        page.keyboard.down("w")
        time.sleep(0.6)
        page.keyboard.up("w")
        moved = page.evaluate("window.__game.mech.position.z")
        if not check("W moves mech forward (-Z)", moved < start["z"] - 1.5, f"z {start['z']:.2f} -> {moved:.2f}"):
            failures.append("movement")

        # 4) sprint into 台北 101 until the collision fires
        page.keyboard.down("Shift")
        page.keyboard.down("w")
        hit = True
        try:
            page.wait_for_function("window.__game.state.destroyed > 0", timeout=15_000)
        except Exception:
            hit = False
        page.keyboard.up("w")
        page.keyboard.up("Shift")

        after = page.evaluate(
            "({destroyed: window.__game.state.destroyed, cost: window.__game.state.totalCost,"
            " alive: window.__game.aliveBuildings,"
            " name: (window.__game.buildings.find(b => !b.alive) || {spec:{name:'-'}}).spec.name,"
            " hudTotal: document.getElementById('total').textContent,"
            " hudLog: document.getElementById('log').textContent})"
        )
        if not check("collision collapses a building", hit and after["alive"] == counts["alive"] - 1, str(after)):
            failures.append("collapse")
        if not check("deduction booked (5,000 萬)", after["cost"] == COST and after["destroyed"] == 1, f"NT$ {after['cost']:,}"):
            failures.append("deduction")
        if not check("HUD shows 扣除 5,000 萬建造費", "扣除 5,000 萬建造費" in after["hudLog"], after["hudLog"][:80]):
            failures.append("hud log")
        if not check("HUD total shows 5,000 萬", "5,000" in after["hudTotal"], after["hudTotal"]):
            failures.append("hud total")

        # 5) collapse animation actually rotates the building about its base edge
        page.wait_for_function("window.__game.collapses[0] && window.__game.collapses[0].done", timeout=10_000)
        time.sleep(0.3)
        tilt = page.evaluate(
            "(() => { const c = window.__game.collapses[0]; if (!c) return -1;"
            " const q = c.pivot.quaternion; return 2 * Math.acos(Math.min(1, Math.abs(q.w))); })()"
        )
        if not check("collapse animation tilts the tower flat", tilt > 1.35, f"{tilt:.2f} rad (~{tilt * 57.3:.0f}°)"):
            failures.append("collapse animation")

        # 6) no runtime errors (model 404 fallback logs info, not error)
        check("no console errors", not console_errors, "; ".join(console_errors[:3]))
        if console_errors:
            failures.append("console errors")

        # 7) 取一張可看的畫面：關掉開始遮罩，退到能看見倒塌大樓的位置
        page.evaluate(
            "document.getElementById('overlay').classList.add('hidden');"
            "window.__game.teleport(14, 12);"
        )
        time.sleep(1.0)
        page.screenshot(path=args.screenshot)
        size = Path(args.screenshot).stat().st_size
        check("screenshot captured", size > 20_000, f"{args.screenshot} ({size // 1024} KB)")
        if size <= 20_000:
            failures.append("screenshot")

        # 8) 手機（H5）模擬：Pixel 5、觸控、虛擬搖桿、拖曳轉視角
        page.close()   # 關掉桌機頁，避免兩個 WebGL 同時跑把 headless 的 FPS 拉到見底
        run_mobile(browser, p, url, failures)

        browser.close()

    server.shutdown() if server else None
    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} check(s): {', '.join(failures)})")
        return 1
    print("RESULT: PASS (desktop + mobile/H5: rendering, movement, collision, collapse, deduction, HUD)")
    return 0


def touch(cdp, kind: str, points: list[tuple[float, float]]) -> None:
    cdp.send(
        "Input.dispatchTouchEvent",
        {
            "type": kind,
            "touchPoints": [{"x": x, "y": y, "id": i + 1} for i, (x, y) in enumerate(points)],
        },
    )


def run_mobile(browser, p, url, failures: list[str]) -> None:
    """手機情境：觸控搖桿移動、拖曳轉視角、撞倒大樓照樣記 5,000 萬。"""
    print("\n--- mobile (Pixel 5, touch) ---")
    device = dict(p.devices["Pixel 5"])
    ctx = browser.new_context(**device)
    page = ctx.new_page()

    errors: list[str] = []

    def on_console(msg):
        if msg.type != "error":
            return
        if "assets/models/" in (msg.location or {}).get("url", ""):
            return
        errors.append(msg.text)

    page.on("console", on_console)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

    page.goto(url, wait_until="load")
    page.wait_for_function("window.__game && window.__game.state.ready", timeout=30_000)
    time.sleep(0.5)

    vp = page.viewport_size or {"width": 393, "height": 851}
    if not check(
        "mobile detected as touch device",
        page.evaluate("window.__game.isCoarse") is True,
        f"viewport {vp['width']}x{vp['height']}",
    ):
        failures.append("mobile detect")

    stick_display = page.eval_on_selector("#stick", "el => getComputedStyle(el).display")
    if not check("virtual joystick visible", stick_display == "block", f"display={stick_display}"):
        failures.append("joystick visible")

    # 觸控開始
    page.tap("#overlay")
    time.sleep(0.4)
    started = page.evaluate("window.__game.started")
    overlay_hidden = page.eval_on_selector("#overlay", "el => el.classList.contains('hidden')")
    if not check("tap starts the game", started and overlay_hidden):
        failures.append("tap start")

    cdp = ctx.new_cdp_session(page)

    # 拖曳轉視角（右側往左拉 → yaw 變大）
    yaw0 = page.evaluate("window.__game.input.look.yaw")
    sx, sy = vp["width"] * 0.8, vp["height"] * 0.45
    touch(cdp, "touchStart", [(sx, sy)])
    for i in range(1, 7):
        touch(cdp, "touchMove", [(sx - i * 16, sy)])
        time.sleep(0.02)
    touch(cdp, "touchEnd", [])
    time.sleep(0.2)
    yaw1 = page.evaluate("window.__game.input.look.yaw")
    if not check("drag rotates camera", abs(yaw1 - yaw0) > 0.15, f"yaw {yaw0:.2f} -> {yaw1:.2f}"):
        failures.append("touch look")
    page.evaluate("window.__game.input.look.yaw = 0")  # 拉回正前方朝 101

    page.screenshot(path=str(ARTIFACTS / "smoke-mobile.png"))

    # 搖桿：往上推到底 = 加速前進，直到撞上台北 101
    box = page.eval_on_selector(
        "#stick", "el => { const r = el.getBoundingClientRect();"
        " return {cx: r.left + r.width / 2, cy: r.top + r.height / 2}; }"
    )
    z0 = page.evaluate("window.__game.mech.position.z")
    cx, cy = box["cx"], box["cy"]
    touch(cdp, "touchStart", [(cx, cy)])
    for i in range(1, 7):
        touch(cdp, "touchMove", [(cx, cy - i * 9)])
        time.sleep(0.03)
    time.sleep(0.8)
    z1 = page.evaluate("window.__game.mech.position.z")
    stick_read = page.evaluate("({x: window.__game.input.stick.x, y: window.__game.input.stick.y})")
    if not check(
        "joystick moves mech forward",
        z1 < z0 - 3 and stick_read["y"] > 0.8,
        f"z {z0:.1f} -> {z1:.1f}, stick={stick_read}",
    ):
        failures.append("joystick movement")

    hit = True
    try:
        page.wait_for_function("window.__game.state.destroyed > 0", timeout=30_000)
    except Exception:
        hit = False
    touch(cdp, "touchEnd", [])

    m = page.evaluate(
        "({destroyed: window.__game.state.destroyed, cost: window.__game.state.totalCost,"
        " hud: document.getElementById('log').textContent,"
        " stick: {x: window.__game.input.stick.x, y: window.__game.input.stick.y}})"
    )
    if not check("mobile collision collapses + deducts", hit and m["cost"] == COST, str(m)[:110]):
        failures.append("mobile collapse")
    if not check("mobile HUD records 扣除 5,000 萬建造費", "扣除 5,000 萬建造費" in m["hud"]):
        failures.append("mobile hud")
    if not check("joystick resets on release", abs(m["stick"]["x"]) < 0.01 and abs(m["stick"]["y"]) < 0.01):
        failures.append("joystick reset")

    page.evaluate("window.__game.teleport(14, 12)")
    time.sleep(1.0)
    shot = ARTIFACTS / "smoke-mobile-collapse.png"
    page.screenshot(path=str(shot))
    if not check("mobile screenshot captured", shot.stat().st_size > 20_000, f"{shot.name} ({shot.stat().st_size // 1024} KB)"):
        failures.append("mobile screenshot")

    check("no console errors (mobile)", not errors, "; ".join(errors[:3]))
    if errors:
        failures.append("mobile console errors")

    ctx.close()


if __name__ == "__main__":
    sys.exit(main())
