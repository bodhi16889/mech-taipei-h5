#!/usr/bin/env python3
"""Tripo3D → 本專案的 GLB 模型生成管線（text_to_model）。

用法（API key 只留在本機，遊戲端不接觸任何金鑰）：

    # 產生專案預設的兩個模型（機甲 + 台北 101）
    python tripo.py --all

    # 只產生其中一個，或自訂 prompt
    python tripo.py --name mech --prompt "a boxy bipedal demolition mech robot"

    # 不想花點數：只看會送出的請求
    python tripo.py --all --dry-run

    # 任務已建立但下載失敗／超時，用同一個 task_id 續抓
    python tripo.py --name taipei101 --resume <task_id>

金鑰來源優先序：--api-key → 環境變數 TRIPO_API_KEY → 專案 .env → C:\\icppython\\.env
（`.env` 內一行：TRIPO_API_KEY=tsk_xxx）

輸出：assets/models/<name>.glb + assets/models/<name>.meta.json（prompt/task_id/sha256，供追溯）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = ROOT / "assets" / "models"
DEFAULT_API_BASE = "https://api.tripo3d.ai/v2/openapi"
ENV_FILES = [ROOT / ".env", Path(r"C:\icppython\.env")]

# 專案要用的模型：prompt 針對「低面數、遊戲用、朝向正確」調過
MODELS: dict[str, dict] = {
    "mech": {
        "prompt": (
            "A compact bipedal demolition mech robot, boxy industrial armor plating, "
            "dark grey and white metal panels, glowing cyan cockpit visor, heavy shoulder pads, "
            "thick legs and feet, small antenna, game-ready low poly, clean topology, "
            "standing straight in T-pose, facing forward"
        ),
        "face_limit": 12000,
        "credits": 20,   # text_to_model + standard texture ≈ 20 credits ≈ US$0.20
        "scale_note": "遊戲內會自動縮到 4.2m 高、置中、貼地（CONFIG.models.mechTargetHeight）",
    },
    "taipei101": {
        "prompt": (
            "Taipei 101 skyscraper as a standalone building, stacked inverted-trapezoid sections "
            "tapering upward, blue-green glass curtain wall with illuminated windows, "
            "steel trim between sections, tall spire on top, base sits on flat ground, "
            "game-ready low poly, clean topology, centered on origin"
        ),
        "face_limit": 20000,
        "credits": 20,
        "scale_note": "遊戲內會自動縮到原方塊塔同高，並依 CITY 設定定位",
    },
}


class ApiError(RuntimeError):
    def __init__(self, status: int, payload: dict | None, raw: str = "") -> None:
        self.status = status
        self.payload = payload or {}
        msg = self.payload.get("message") or raw or f"HTTP {status}"
        suggestion = self.payload.get("suggestion") or ""
        super().__init__(f"HTTP {status}: {msg}" + (f"（{suggestion}）" if suggestion else ""))


def resolve_api_key(cli_key: str | None) -> str | None:
    if cli_key:
        return cli_key.strip()
    env = os.environ.get("TRIPO_API_KEY", "").strip()
    if env:
        return env
    for env_file in ENV_FILES:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip().lstrip("export ").strip() == "TRIPO_API_KEY":
                return value.strip().strip("'\"")
    return None


def request_json(method: str, url: str, api_key: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = None
        raise ApiError(exc.code, parsed, body) from exc
    except urllib.error.URLError as exc:
        raise ApiError(0, None, f"連不上 Tripo API：{exc.reason}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        raise ApiError(0, None, f"回應不是 JSON：{body[:200]}") from None

    if parsed.get("code") not in (0, None):
        raise ApiError(200, parsed)
    return parsed


def create_task(api_base: str, api_key: str, name: str, spec: dict, args) -> str:
    payload = {
        "type": "text_to_model",
        "prompt": spec["prompt"],
        "texture": True,
        "pbr": True,
    }
    if spec.get("face_limit"):
        payload["face_limit"] = int(spec["face_limit"])
    if args.model_version:
        payload["model_version"] = args.model_version
    if args.negative_prompt:
        payload["negative_prompt"] = args.negative_prompt

    credits = int(spec.get("credits") or 20)
    print(f"[{name}] 預估花費：約 {credits} credits ≈ US${credits * 0.01:.2f}")

    if args.dry_run:
        print(f"[dry-run] POST {api_base}/task")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return ""

    resp = request_json("POST", f"{api_base}/task", api_key, payload)
    task_id = (resp.get("data") or {}).get("task_id")
    if not task_id:
        raise ApiError(0, resp, "回應沒有 task_id")
    print(f"[{name}] 任務已建立：{task_id}")
    return task_id


def wait_for_task(api_base: str, api_key: str, task_id: str, interval: float, timeout: float) -> dict:
    started = time.time()
    last_progress = -1
    while True:
        resp = request_json("GET", f"{api_base}/task/{task_id}", api_key)
        data = resp.get("data") or {}
        status = data.get("status", "unknown")
        progress = int(data.get("progress") or 0)
        if progress != last_progress or status != "running":
            print(f"    status={status} progress={progress}%", flush=True)
            last_progress = progress
        if status == "success":
            return data
        if status in {"failed", "cancelled", "banned", "expired", "unknown"}:
            raise ApiError(0, data, f"任務狀態 {status}")
        if time.time() - started > timeout:
            raise ApiError(0, data, f"等待逾時（{timeout:.0f}s），可稍後用 --resume {task_id} 續抓")
        time.sleep(interval)


def pick_model_url(output: dict) -> str | None:
    # 官方說明：model / pbr_model / base_model 都是 5 分鐘內有效的下載連結
    for key in ("pbr_model", "model", "base_model", "model_url"):
        if output.get(key):
            return output[key]
    return None


def download(url: str, dest: Path) -> tuple[int, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    tmp.replace(dest)
    return size, digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用 Tripo3D text_to_model 產生遊戲用 GLB。")
    parser.add_argument("--name", help=f"模型名稱（{', '.join(MODELS)}）或任意新名稱（需搭配 --prompt）")
    parser.add_argument("--prompt", help="自訂 prompt（覆蓋 --name 的預設 prompt）")
    parser.add_argument("--all", action="store_true", help="依序產生 MODELS 內所有預設模型")
    parser.add_argument("--list", action="store_true", help="列出預設模型與 prompt")
    parser.add_argument("--api-key", help="Tripo API key（建議改用環境變數 TRIPO_API_KEY 或 .env）")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help=argparse.SUPPRESS)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="輸出目錄（預設 assets/models）")
    parser.add_argument("--model-version", help="例如 v2.5-20250123；不給就用 API 預設")
    parser.add_argument("--negative-prompt", default="low quality, blurry, extra limbs, text, watermark")
    parser.add_argument("--resume", metavar="TASK_ID", help="略過建立任務，直接抓既有 task_id 的結果")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true", help="只印出會送出的請求，不呼叫 API")
    parser.add_argument(
        "--allow-credits", action="store_true",
        help="明確同意消耗 Tripo 點數（API 為點數制，預設拒絕，避免意外花錢）",
    )
    args = parser.parse_args(argv)

    if args.list:
        for name, spec in MODELS.items():
            print(f"{name}: face_limit={spec.get('face_limit')}  {spec['scale_note']}")
            print(f"  prompt: {spec['prompt']}")
        return 0

    if args.all:
        names = list(MODELS)
    elif args.name:
        names = [args.name]
    else:
        parser.error("請給 --name、--all 或 --list")

    specs: dict[str, dict] = {}
    for name in names:
        spec = dict(MODELS.get(name, {}))
        if args.prompt:
            spec["prompt"] = args.prompt
            spec.setdefault("scale_note", "自訂 prompt")
        if not spec.get("prompt"):
            parser.error(f"未知模型「{name}」，請用 --prompt 指定描述")
        specs[name] = spec

    if not args.resume and not args.dry_run:
        # 付費守門：預設不送出生成請求，避免意外花點數（使用者 2026-11-04 決定先不付費）
        if not args.allow_credits:
            print("Tripo API 是點數制（1 credit = US$0.01；text_to_model + texture ≈ 20 credits ≈ US$0.20／模型），", file=sys.stderr)
            print("已依設定暫停付費生成，tripo.py 預設不送出請求。", file=sys.stderr)
            print("  · 真的要花點數：加 --allow-credits", file=sys.stderr)
            print("  · 不花錢：在 Tripo Studio 網頁用免費額度生成後匯出 GLB 放進 assets/models/（見 README）", file=sys.stderr)
            print("  · 已有任務只下載：--resume <task_id>（不新增花費）", file=sys.stderr)
            return 4

        api_key = resolve_api_key(args.api_key)
        if not api_key:
            print("找不到 Tripo API key。", file=sys.stderr)
            print("  1) https://platform.tripo3d.ai/ → API Keys 建立（tsk_ 開頭）", file=sys.stderr)
            print("  2) 設環境變數：setx TRIPO_API_KEY tsk_xxx（重開終端）", file=sys.stderr)
            print(f"  3) 或寫進 {ENV_FILES[0]} 一行：TRIPO_API_KEY=tsk_xxx", file=sys.stderr)
            return 2
    else:
        api_key = args.api_key or os.environ.get("TRIPO_API_KEY") or "dry-run-key"

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    results: list[dict] = []

    for name in names:
        spec = specs[name]
        print(f"\n=== {name} ===")
        try:
            task_id = args.resume or create_task(args.api_base, api_key, name, spec, args)
            if args.dry_run:
                results.append({"name": name, "dry_run": True})
                continue

            data = wait_for_task(args.api_base, api_key, task_id, args.poll_interval, args.timeout)
            url = pick_model_url(data.get("output") or {})
            if not url:
                raise ApiError(0, data, "任務成功但 output 沒有模型連結")

            dest = out_dir / f"{name}.glb"
            size, sha = download(url, dest)
            meta = {
                "name": name,
                "prompt": spec["prompt"],
                "task_id": task_id,
                "model_version": args.model_version or "api-default",
                "status": data.get("status"),
                "bytes": size,
                "sha256": sha,
                "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": f"{args.api_base}/task/{task_id}",
            }
            (out_dir / f"{name}.meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            mb = size / (1024 * 1024)
            print(f"[{name}] ✅ {dest}  {mb:.2f} MB  sha256={sha[:12]}…")
            if mb > 8:
                print(f"[{name}] ⚠️  {mb:.1f} MB 對手機偏大：考慮 --face-limit 或 Tripo 後台的減面/壓縮選項")
            print(f"[{name}] 下一步：重新整理遊戲頁面即可看到模型（找不到就沿用方塊版）")
            results.append({"name": name, "task_id": task_id, "bytes": size, "sha256": sha})
        except ApiError as exc:
            print(f"[{name}] ❌ {exc}", file=sys.stderr)
            return 3

    if args.dry_run:
        print("\n（--dry-run：未呼叫 API、未產生檔案）")
    else:
        print(f"\n完成 {len(results)} 個模型（{started:%Y-%m-%d %H:%M UTC} 開始）→ {out_dir}")
        print("重新發佈到 Pages： .\\publish-pages.ps1 -Owner bodhi16889 -Repo mech-taipei-h5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
