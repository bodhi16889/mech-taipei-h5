# assets/models

這裡放遊戲會自動載入的 **GLB 模型**；檔案不存在時會靜默 fallback 回程序化方塊版本。

| 檔名 | 用途 | 目標高度 |
| :--- | :--- | :--- |
| `mech.glb` | 玩家機甲 | 4.2 m（`CONFIG.models.mechTargetHeight`） |
| `taipei101.glb` | 台北 101 地標 | 與原方塊塔同高（自動量測） |

其他地標：在 `CONFIG.models.buildings` 加上 `{ <CITY 的 id>: 'assets/models/<檔名>.glb' }`。

## 用 Tripo3D 自動生成

```powershell
setx TRIPO_API_KEY tsk_xxxx     # 重開終端
python tripo.py --all --dry-run # 先看會送出的請求（不花點數）
python tripo.py --all           # 生成 mech.glb + taipei101.glb
```

`tripo.py` 會一併寫出 `<name>.meta.json`：

```json
{
  "name": "mech",
  "prompt": "...",
  "task_id": "ef731ad6-...",
  "model_version": "api-default",
  "bytes": 1834021,
  "sha256": "…",
  "downloaded_at": "2026-11-04T05:12:33+00:00"
}
```

下載連結只有 5 分鐘有效，所以腳本會「一拿到 URL 就下載」；若任務已建立但下載失敗，
用 `python tripo.py --name mech --resume <task_id>` 續抓（meta.json 內有 task_id）。

## 手動匯出

- 格式 **GLB**（單檔、貼圖內嵌），Y-up。
- 面數 ≤ 30k、貼圖 ≤ 2048²，避免手機卡頓（> 8 MB 時 `tripo.py` 會警告）。
- 物件原點放在**腳底／地基中心**最好對位；`fitToGround()` 仍會自動置中並貼地。
- 朝向與遊戲相反（Tripo 常是正面朝 `+Z`）時，改 `CONFIG.models.mechRotationY` /
  `buildingRotationY`，不用回頭改模型。
