#!/usr/bin/env python3
"""驗證「GLB 替換方塊」這條路真的可用——不需要 Tripo 點數。

做法：
  1. 用純 Python 產生兩個合法的小 GLB（方塊機甲 1×4×1、方塊塔 18×60×18）
  2. 複製到 assets/models/mech.glb 與 taipei101.glb
  3. 用 Playwright 開頁面，檢查 console 有「已套用…GLB」、方塊機甲已被清掉、
     building.modelUrl 有值、機甲仍可移動並撞倒大樓
  4. finally 一定刪掉測試 GLB，回歸方塊版（不會把假模型留在專案裡）

    python verify_models.py
"""
from __future__ import annotations

import json
import re
import struct
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "assets" / "models"
FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def make_box_glb(path: Path, sx: float, sy: float, sz: float) -> None:
    """寫一個最小可用的 GLB：單一 box mesh + 基本 PBR 材質。"""
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    verts = [
        (-hx, 0, -hz), (hx, 0, -hz), (hx, 0, hz), (-hx, 0, hz),
        (-hx, sy, -hz), (hx, sy, -hz), (hx, sy, hz), (-hx, sy, hz),
    ]
    idx = [0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6, 0, 4, 5, 0, 5, 1,
           1, 5, 6, 1, 6, 2, 2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0]
    positions = b"".join(struct.pack("<3f", *v) for v in verts)
    indices = b"".join(struct.pack("<H", i) for i in idx)
    while len(indices) % 4:
        indices += b"\x00"

    gltf = {
        "asset": {"version": "2.0", "generator": "mech-taipei verify_models"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "box"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.85, 0.9, 0.95, 1.0],
                "metallicFactor": 0.4,
                "roughnessFactor": 0.5,
            },
            "emissiveFactor": [0.05, 0.15, 0.2],
        }],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(verts), "type": "VEC3",
             "min": [-hx, 0, -hz], "max": [hx, sy, hz]},
            {"bufferView": 1, "componentType": 5123, "count": len(idx), "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions), "target": 34962},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices), "target": 34963},
        ],
        "buffers": [{"byteLength": len(positions) + len(indices)}],
    }
    bin_chunk = positions + indices
    json_chunk = json.dumps(gltf, separators=(",", ":")).encode()
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    bin_chunk += b"\x00" * ((4 - len(bin_chunk) % 4) % 4)

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    out = bytearray()
    out += b"glTF" + struct.pack("<II", 2, total)
    out += struct.pack("<I", len(json_chunk)) + b"JSON" + json_chunk
    out += struct.pack("<I", len(bin_chunk)) + b"BIN\x00" + bin_chunk
    path.write_bytes(bytes(out))


def main() -> int:
    mech_tmp, tower_tmp = MODELS / "mech.glb", MODELS / "taipei101.glb"
    backups: dict[Path, bytes] = {}
    for p in (mech_tmp, tower_tmp):
        if p.is_file():
            backups[p] = p.read_bytes()

    try:
        make_box_glb(mech_tmp, 1.0, 4.0, 1.0)
        make_box_glb(tower_tmp, 18.0, 60.0, 18.0)
        check("測試 GLB 已產生", mech_tmp.stat().st_size > 100 and tower_tmp.stat().st_size > 100,
              f"mech={mech_tmp.stat().st_size}B tower={tower_tmp.stat().st_size}B")

        import functools
        import http.server
        import socketserver
        import threading

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        handler.log_message = lambda *a, **k: None

        class Server(socketserver.TCPServer):
            allow_reuse_address = True

        server = Server(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/index.html"

        logs: list[str] = []
        errors: list[str] = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
                )
                page = browser.new_page(viewport={"width": 1024, "height": 640})
                page.on("console", lambda m: (logs.append(m.text), errors.append(m.text) if m.type == "error" else None))
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url, wait_until="load")
                page.wait_for_function("window.__game && window.__game.state.ready", timeout=30_000)
                time.sleep(1.0)

                state = page.evaluate(
                    "({modelUrl: window.__game.mech.userData.modelUrl || null,"
                    " blockoutChildren: window.__game.mech.children[0].children.length,"
                    " buildings: window.__game.buildings.filter(b => b.modelUrl).map(b => b.spec.id),"
                    " mechBox: (() => { const b = new (window.__game.mech.constructor)(); return null; })() })"
                )
                check("機甲已換成 GLB", bool(state["modelUrl"]), str(state["modelUrl"]))
                check("方塊機甲零件已清空", state["blockoutChildren"] == 0, f"children={state['blockoutChildren']}")
                check("台北 101 已換成 GLB", "taipei101" in state["buildings"], str(state["buildings"]))
                check("console 有套用訊息", any("已套用機甲 GLB" in m for m in logs) and
                      any("已套用建物 GLB" in m for m in logs))

                # 模型縮放/置中：機甲高度應接近 CONFIG.models.mechTargetHeight
                dims = page.evaluate(
                    "(() => { const THREEBox = window.__game.scene.children.find(o => o.isGroup);"
                    " const m = window.__game.mech; m.updateMatrixWorld(true);"
                    " const b = new (m.children[0].geometry ? Object : Object)(); return null; })()"
                )
                height = page.evaluate(
                    "(() => { const m = window.__game.mech; m.updateMatrixWorld(true);"
                    " const min = { y: Infinity }, max = { y: -Infinity };"
                    " m.traverse(n => { if (!n.geometry) return; n.geometry.computeBoundingBox();"
                    "  const bb = n.geometry.boundingBox.clone(); bb.applyMatrix4(n.matrixWorld);"
                    "  min.y = Math.min(min.y, bb.min.y); max.y = Math.max(max.y, bb.max.y); });"
                    " return +(max.y - min.y).toFixed(2); })()"
                )
                target = page.evaluate("window.__game.CONFIG.models.mechTargetHeight")
                check("機甲縮放到目標高度", abs(height - target) < 0.4, f"height={height} target={target}")

                # 仍可移動並撞倒大樓
                page.evaluate("document.getElementById('overlay').classList.add('hidden')")
                page.keyboard.down("Shift")
                page.keyboard.down("w")
                hit = True
                try:
                    page.wait_for_function("window.__game.state.destroyed > 0", timeout=25_000)
                except Exception:
                    hit = False
                page.keyboard.up("w")
                page.keyboard.up("Shift")
                check("換模型後仍能撞倒大樓記帳",
                      hit and page.evaluate("window.__game.state.totalCost") == 50_000_000)
                check("沒有 console error", not [e for e in errors if "assets/models" not in e],
                      "; ".join(errors[:2]))
                page.screenshot(path=str(ROOT / "artifacts" / "models-glb-applied.png"))
                browser.close()
        finally:
            server.shutdown()
    finally:
        for p in (mech_tmp, tower_tmp):
            if p in backups:
                p.write_bytes(backups[p])
            elif p.exists():
                p.unlink()
        meta = MODELS / "mech.meta.json"
        if meta.exists():
            meta.unlink()

    print()
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)}: {', '.join(FAILS)})")
        return 1
    print("RESULT: PASS (GLB 載入 → 替換方塊 → 縮放/置中 → 仍可遊玩；測試檔已清除)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
