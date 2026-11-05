"""Verify threejs-mech-taipei/v3/index.html — the GDD vertical slice.

Asserts the GDD's core loop actually works, in order:
  1. contract board lists 4 contracts (3 市政 + 1 黑市)
  2. selecting a contract builds the mech (19 parts) and shows the HUD
  3. 洩壓 (E at the valve) flips the red-line hazard off
  4. cutting a pressurised red line explodes → penalty recorded
  5. an untethered load-bearing strut topples the mech → landmark penalty
  6. a tethered strut can be cut safely and is salvaged
  7. cutting both chest plates exposes the core → meltdown timer counts down
  8. extracting the core needs the jetpack (ground distance is too far)
  9. quota + core → 收工 → settlement ledger, credits, upgrades
 10. real mouse input reaches the cutter (pointer lock path)
 11. mobile: touch start, stick moves, no horizontal overflow
 12. reduced motion: playable, no shake errors

Usage:  python verify_v3.py [--headed] [--port 0]
Exit:   0 = pass, 1 = failure
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
CHROME_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


def serve(directory: Path, port: int) -> socketserver.TCPServer:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *a, **k: None

    class Server(socketserver.TCPServer):
        allow_reuse_address = True

    server = Server(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def attach_errors(page, sink: list[str]) -> None:
    def on_console(msg):
        if msg.type != "error":
            return
        if any(k in msg.text for k in ("manifest", "favicon", "apple-touch")):
            return
        sink.append(msg.text)

    page.on("console", on_console)
    page.on("pageerror", lambda e: sink.append(f"pageerror: {e}"))


def open_game(browser, url: str, **ctx):
    page = browser.new_page(viewport={"width": 1280, "height": 720}, **ctx)
    errs: list[str] = []
    attach_errors(page, errs)
    page.goto(url, wait_until="load")
    page.wait_for_function("window.__v3 && window.__v3.state.frames > 0", timeout=30_000)
    return page, errs


def desktop(browser, url: str, failures: list[str]) -> None:
    page, errs = open_game(browser, url)

    # 1) contract board
    cards = page.evaluate("window.__v3.contracts")
    kinds = page.evaluate("[...document.querySelectorAll('.contract .tagline')].map(e => e.textContent)")
    ok = len(cards) == 4 and "BLACK MARKET" in kinds
    if not check("contract board: 3 市政 + 1 黑市", ok, f"{len(cards)} cards · {kinds}"):
        failures.append("contract board")
    page.screenshot(path=str(ARTIFACTS / "v3-menu.png"))

    # 2) start
    page.evaluate("window.__v3.startContract('s1')")
    page.wait_for_timeout(700)
    st = page.evaluate("window.__v3.state")
    parts = page.evaluate("window.__v3.parts")
    if not check("contract builds the mech", st["screen"] == "site" and len(parts) == 19, f"{len(parts)} parts"):
        failures.append("build")
    page.screenshot(path=str(ARTIFACTS / "v3-site.png"))

    # 3) depressurise
    page.evaluate("window.__v3.teleport(2.2, 0, 4.2); window.__v3.pressE()")
    page.wait_for_timeout(250)
    if not check("E at the valve depressurises", page.evaluate("window.__v3.state.depressurized")):
        failures.append("depressurise")

    page.evaluate("window.__v3.cutPart('line-red')")
    page.wait_for_timeout(250)
    if not check("red line cut is safe after 洩壓", page.evaluate("window.__v3.state.penalties") == 0):
        failures.append("safe red line")

    # 4) chest → core
    for pid in ("armor-chest-l", "armor-chest-r"):
        page.evaluate(f"window.__v3.cutPart('{pid}')")
        page.wait_for_timeout(200)
    st = page.evaluate("window.__v3.state")
    if not check("cutting both chest plates exposes the core", st["coreExposed"]):
        failures.append("core expose")
    page.wait_for_timeout(1200)
    left = page.evaluate("window.__v3.state.coreLeft")
    if not check("meltdown timer is counting down", left < 60, f"{left}s left"):
        failures.append("core timer")

    # 5) core needs the jetpack: on the ground it must fail
    page.evaluate("window.__v3.teleport(0, 0, 4.6); window.__v3.lookAt(0, 7.5, 0); window.__v3.pressE()")
    page.wait_for_timeout(250)
    ground_take = page.evaluate("window.__v3.state.coreTaken")
    if not check("core is out of reach from the ground (needs exo-jet)", ground_take is False, str(ground_take)):
        failures.append("core ground gate")

    page.evaluate("window.__v3.teleport(0, 5.2, 4.6); window.__v3.lookAt(0, 7.5, 0); window.__v3.pressE()")
    page.wait_for_timeout(250)
    if not check("jetpack height + E extracts the core", page.evaluate("window.__v3.state.coreTaken")):
        failures.append("core extract")

    # 6) tether + cut a strut = safe salvage
    page.evaluate("window.__v3.tetherPart('strut-leg-0'); window.__v3.cutPart('strut-leg-0')")
    page.wait_for_timeout(1600)
    st = page.evaluate("window.__v3.state")
    if not check("tethered strut cuts safely and is salvaged", not st["toppled"] and st["salvaged"] >= 2,
                 f"toppled={st['toppled']} salvaged={st['salvaged']}"):
        failures.append("tether strut")

    # 7) quota → 收工 → settlement
    page.evaluate("window.__v3.tetherPart('armor-head'); window.__v3.cutPart('armor-head')")
    page.wait_for_timeout(1600)
    st = page.evaluate("window.__v3.state")
    if not check("quota met", st["quotaMet"], f"{st['salvaged']} salvaged"):
        failures.append("quota")
    credits_before = st["credits"]
    page.evaluate("window.__v3.pressE()")
    page.wait_for_timeout(700)
    st = page.evaluate("window.__v3.state")
    ledger = page.evaluate("document.getElementById('ledger').textContent.replace(/\\s+/g,' ')")
    if not check("收工 settles the contract", st["screen"] == "debrief" and st["credits"] > credits_before,
                 f"credits {credits_before} -> {st['credits']}"):
        failures.append("settlement")
    if not check("ledger shows salvage / bonus / total", "回收零件價值" in ledger and "本次入帳" in ledger, ledger[:90]):
        failures.append("ledger")

    # 8) upgrade purchase
    up = page.evaluate("""(() => {
        const b = document.querySelector('.up[data-id="cutter"]');
        if (!b) return null;
        const before = window.__v3.state.credits;
        b.click();
        return { before, after: window.__v3.state.credits };
    })()""")
    if not check("upgrade purchase spends credits", up and up["after"] < up["before"], str(up)):
        failures.append("upgrade")
    page.screenshot(path=str(ARTIFACTS / "v3-debrief.png"))

    # 9) untethered strut topples (fresh contract, isolated)
    page.evaluate("window.__v3.startContract('s2')")
    page.wait_for_timeout(600)
    page.evaluate("window.__v3.cutPart('strut-leg-0')")
    page.wait_for_timeout(400)
    st = page.evaluate("window.__v3.state")
    if not check("untethered strut topples the mech → landmark penalty", st["toppled"] and st["penalties"] >= 1,
                 f"toppled={st['toppled']} penalties={st['penalties']}"):
        failures.append("topple")

    # 10) red line without depressurising explodes
    page.evaluate("window.__v3.cutPart('line-red')")
    page.wait_for_timeout(400)
    st = page.evaluate("window.__v3.state")
    if not check("pressurised red line explodes → penalty", st["penalties"] >= 2, f"penalties={st['penalties']}"):
        failures.append("explosion")

    check("no console errors", not errs, "; ".join(errs[:3]))
    if errs:
        failures.append("console")
    page.close()


def mouse_input(browser, url: str, failures: list[str]) -> None:
    print("\n--- real mouse input ---")
    page, errs = open_game(browser, url)
    page.evaluate("window.__v3.startContract('s1')")
    page.wait_for_timeout(600)
    page.mouse.click(640, 360)          # 取得 pointer lock（先鎖定，再校正視角）
    page.wait_for_timeout(400)
    locked = page.evaluate("document.pointerLockElement !== null")
    page.evaluate("window.__v3.facePart('armor-shoulder-0'); window.__v3.setTool('cutter')")
    page.wait_for_timeout(400)
    aim = page.evaluate("window.__v3.aim()")
    page.mouse.down()
    page.wait_for_timeout(3200)
    page.mouse.up()
    page.wait_for_timeout(300)
    parts = page.evaluate("window.__v3.parts")
    hit = next((p for p in parts if aim and p["id"] == aim["id"]), None)
    ok = locked and aim is not None and hit is not None and (hit["cut"] > 0 or hit["state"] != "intact")
    if not check("hold-LMB cuts the part through the real pointer-lock path", ok,
                 f"locked={locked} aim={aim} part={hit}"):
        failures.append("mouse cut")
    if not check("no console errors (mouse run)", not errs, "; ".join(errs[:2])):
        failures.append("mouse console")
    page.close()


def reduced_motion(browser, url: str, failures: list[str]) -> None:
    print("\n--- reduced motion ---")
    ctx = browser.new_context(viewport={"width": 1280, "height": 720}, reduced_motion="reduce")
    page = ctx.new_page()
    errs: list[str] = []
    attach_errors(page, errs)
    page.goto(url, wait_until="load")
    page.wait_for_function("window.__v3 && window.__v3.state.frames > 0", timeout=30_000)
    page.evaluate("window.__v3.startContract('s1')")
    page.wait_for_timeout(500)
    page.evaluate("window.__v3.cutPart('strut-leg-0')")   # 傾倒但 reduced motion 不震動
    page.wait_for_timeout(400)
    st = page.evaluate("window.__v3.state")
    ok = check("plays with reduced motion", st["screen"] == "site" and not errs, f"toppled={st['toppled']}")
    if not ok:
        failures.append("reduced motion")
    ctx.close()


def mobile(browser, url: str, failures: list[str]) -> None:
    print("\n--- mobile (Pixel 5, touch) ---")
    ctx = browser.new_context(viewport={"width": 393, "height": 851}, device_scale_factor=2.75,
                              is_mobile=True, has_touch=True,
                              user_agent="Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36")
    page = ctx.new_page()
    errs: list[str] = []
    attach_errors(page, errs)
    page.goto(url, wait_until="load")
    page.wait_for_function("window.__v3 && window.__v3.state.frames > 0", timeout=30_000)
    page.tap(".contract[data-id='s1']")
    page.wait_for_timeout(800)
    if not check("tap selects a contract on phone", page.evaluate("window.__v3.state.screen") == "site"):
        failures.append("mobile start")

    box = page.evaluate("(() => { const r = document.getElementById('stick').getBoundingClientRect(); return {x: r.left + r.width/2, y: r.top + r.height/2}; })()")
    p0 = page.evaluate("window.__v3.player")
    page.mouse.move(box["x"], box["y"])
    page.mouse.down()
    page.mouse.move(box["x"], box["y"] - 40, steps=4)
    page.wait_for_timeout(900)
    page.mouse.up()
    page.wait_for_timeout(200)
    p1 = page.evaluate("window.__v3.player")
    dist = ((p1["x"] - p0["x"]) ** 2 + (p1["z"] - p0["z"]) ** 2) ** 0.5
    if not check("virtual stick moves the worker", dist > 0.8, f"{dist:.2f} m"):
        failures.append("mobile stick")

    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if not check("no horizontal overflow on phone", overflow <= 0, f"{overflow}px"):
        failures.append("mobile layout")
    check("no console errors (mobile)", not errs, "; ".join(errs[:2]))
    if errs:
        failures.append("mobile console")
    page.screenshot(path=str(ARTIFACTS / "v3-mobile.png"))
    ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--page", default="index.html", help="相對於 repo 根目錄的遊戲頁面")
    args = ap.parse_args()

    ARTIFACTS.mkdir(exist_ok=True)
    server = serve(ROOT, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/{args.page}"
    print(f"serving {ROOT} → {url}")

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, args=CHROME_ARGS)
        desktop(browser, url, failures)
        mouse_input(browser, url, failures)
        reduced_motion(browser, url, failures)
        mobile(browser, url, failures)
        browser.close()

    server.shutdown()
    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)}: {', '.join(failures)})")
        return 1
    print("RESULT: PASS (contracts, 洩壓, 切割, 繫留, 傾倒罰款, 核心倒數/取出, 結算, 升級, 滑鼠, 手機, reduced motion)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
