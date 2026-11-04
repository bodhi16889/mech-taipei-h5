# assets/models

把 Tripo3D 匯出的 GLB 放在這裡，`index.html` 會自動載入並取代方塊版本；
檔案不存在時會靜默 fallback（瀏覽器 console 會有一行 404，屬預期）。

| 檔名 | 用途 | 目標高度 |
| :--- | :--- | :--- |
| `mech.glb` | 玩家機甲 | 4.2 m（`CONFIG.models.mechTargetHeight`） |
| `taipei101.glb` | 台北 101 地標 | 與原方塊塔同高（自動量測） |

其他地標：在 `CONFIG.models.buildings` 加上 `{ <CITY 的 id>: 'assets/models/<檔名>.glb' }`。

匯出建議：

- 格式 **GLB**（單檔、貼圖內嵌），Y-up，正面朝 `-Z`。
- 面數 ≤ 30k、貼圖 ≤ 2048²，避免行動裝置卡頓。
- 物件原點放在**腳底／地基中心**最好對位；`fitToGround()` 仍會自動置中並貼地。
