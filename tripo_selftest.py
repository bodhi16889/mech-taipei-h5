#!/usr/bin/env python3
"""tripo.py 的離線自我測試：用本機 stub server 驗證「建任務 → 輪詢 → 下載 → 寫 meta」整條管線。

不需要 Tripo 點數、不需要真的 API key。

    python tripo_selftest.py

檢查：
  1. 正常流程：payload 正確、等到 success、GLB 內容正確、meta.json 的 sha256/bytes 正確
  2. 金鑰錯誤：API 回 401 → tripo.py 以 exit 3 結束並印出可讀訊息
  3. 沒有金鑰：以 exit 2 結束並提示如何設定
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FAKE_GLB = b"glTF\x02\x00\x00\x00" + b"\x00" * 256 + b"TRIPO-STUB-PAYLOAD"
STATE = {"posts": [], "polls": 0}
FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 靜音
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v2/openapi/task":
            return self._json(404, {"code": 1004, "message": "not found"})
        auth = self.headers.get("Authorization", "")
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        STATE["posts"].append({"auth": auth, "payload": payload})
        if auth != "Bearer test-key":
            return self._json(401, {"code": 1002, "message": "Authentication failed",
                                    "suggestion": "Check your credentials"})
        self._json(200, {"code": 0, "data": {"task_id": "task-mock-1"}})

    def do_GET(self):
        if self.path.startswith("/v2/openapi/task/"):
            task_id = self.path.rsplit("/", 1)[-1]
            auth = self.headers.get("Authorization", "")
            if auth != "Bearer test-key":
                return self._json(401, {"code": 1002, "message": "Authentication failed",
                                        "suggestion": "Check your credentials"})
            STATE["polls"] += 1
            if STATE["polls"] < 2:
                return self._json(200, {"code": 0, "data": {
                    "task_id": task_id, "status": "running", "progress": 40, "output": {}}})
            base = f"http://127.0.0.1:{PORT}"
            return self._json(200, {"code": 0, "data": {
                "task_id": task_id, "status": "success", "progress": 100,
                "output": {"pbr_model": f"{base}/files/model.glb",
                           "model": f"{base}/files/model.glb"}}})
        if self.path == "/files/model.glb":
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(len(FAKE_GLB)))
            self.end_headers()
            self.wfile.write(FAKE_GLB)
            return
        self._json(404, {"code": 1004, "message": "not found"})


def run_tripo(args: list[str], with_key: bool = True) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "TRIPO_API_KEY"}
    if not with_key:
        env.pop("TRIPO_API_KEY", None)
    return subprocess.run(
        [sys.executable, str(ROOT / "tripo.py"), *args],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )


def main() -> int:
    global PORT
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    PORT = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{PORT}/v2/openapi"
    print(f"stub server: {api}\n")

    with tempfile.TemporaryDirectory() as tmp:
        # 1) 正常流程
        STATE["polls"] = 0
        proc = run_tripo([
            "--name", "mock", "--prompt", "a stub mech",
            "--api-base", api, "--api-key", "test-key",
            "--out-dir", tmp, "--poll-interval", "0.05", "--timeout", "30",
        ])
        glb = Path(tmp) / "mock.glb"
        meta_path = Path(tmp) / "mock.meta.json"
        check("正常流程 exit 0", proc.returncode == 0, f"exit={proc.returncode} {proc.stderr.strip()[:160]}")
        check("任務有建立（POST /task）", len(STATE["posts"]) == 1)
        if STATE["posts"]:
            sent = STATE["posts"][0]
            check("payload type=text_to_model", sent["payload"].get("type") == "text_to_model")
            check("payload 帶入 prompt", sent["payload"].get("prompt") == "a stub mech")
            check("Authorization 使用 Bearer", sent["auth"] == "Bearer test-key")
        check("有輪詢到 success（>=2 次）", STATE["polls"] >= 2, f"polls={STATE['polls']}")
        check("GLB 已下載且內容正確", glb.is_file() and glb.read_bytes() == FAKE_GLB,
              f"{glb.stat().st_size if glb.is_file() else 0} bytes")
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            check("meta.json task_id", meta.get("task_id") == "task-mock-1")
            check("meta.json sha256 正確", meta.get("sha256") == hashlib.sha256(FAKE_GLB).hexdigest())
            check("meta.json bytes 正確", meta.get("bytes") == len(FAKE_GLB))
        else:
            check("meta.json 已產生", False)

        # 2) 金鑰錯誤 → 401，exit 3
        proc = run_tripo([
            "--name", "mock", "--prompt", "x",
            "--api-base", api, "--api-key", "wrong-key",
            "--out-dir", tmp, "--poll-interval", "0.05", "--timeout", "10",
        ])
        check("金鑰錯誤 exit 3", proc.returncode == 3, f"exit={proc.returncode}")
        check("金鑰錯誤訊息可讀", "401" in proc.stderr and "Authentication" in proc.stderr,
              proc.stderr.strip()[:120])

        # 3) 沒有金鑰 → exit 2（用已知模型，才會走到金鑰檢查而不是 argparse 的未知模型錯誤）
        proc = run_tripo(["--name", "mech"], with_key=False)
        check("沒有金鑰 exit 2", proc.returncode == 2, f"exit={proc.returncode}")
        check("沒有金鑰有設定指引", "TRIPO_API_KEY" in proc.stderr, proc.stderr.strip().splitlines()[:1])

    server.shutdown()
    print()
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)}: {', '.join(FAILS)})")
        return 1
    print("RESULT: PASS (create → poll → download → meta，含 401／缺金鑰處理)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
