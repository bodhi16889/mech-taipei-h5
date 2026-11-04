# 台北機甲拆除模擬器 · Three.js（方塊階段 · 桌機 + 手機 H5）

> 🌐 **線上版（手機可直接開）**：<https://bodhi16889.github.io/mech-taipei-h5/>
> 公開原始碼（只含遊戲）：<https://github.com/bodhi16889/mech-taipei-h5>
> 用 `publish-pages.ps1` 發佈，實作與驗證記錄見下方「區網還是不通？」。

用一個 HTML 檔就能跑的 Three.js 3D 小遊戲：地面 + 台北大樓方塊 + 機甲。
桌機用 **WASD + 滑鼠（Pointer Lock）**，手機用 **左下虛擬搖桿 + 右側拖曳轉視角（H5）**。
機甲撞上大樓 → 大樓往撞擊方向倒塌 → 畫面右上角記一筆 **「扣除 5,000 萬建造費」**。

目前是 **階段 1（方塊版）**，程式已預留 **階段 2：Tripo3D GLB 模型替換** 的載入路徑
（見下方「換成 Tripo3D 模型」）。

## 檔案

| 檔案 | 說明 |
| :--- | :--- |
| `index.html` | 遊戲本體（場景／大樓／機甲／碰撞／倒塌／HUD／輸入／模型載入），桌機與手機同一份 |
| `manifest.webmanifest` | PWA manifest（加到主畫面，`display: fullscreen`）|
| `assets/icon-192.png` / `icon-512.png` | 主畫面圖示 |
| `assets/models/` | Tripo3D GLB 放這裡（`mech.glb`、`taipei101.glb`）|
| `verify_smoke.py` | 桌機 + 手機（Pixel 5 觸控模擬）自動驗證，輸出 `artifacts/*.png`；`--base-url` 可改測 tunnel／Pages 網址 |
| `tunnel.ps1` | Cloudflare Quick Tunnel（`-Status`／`-Stop`，內建 7844 前置檢查）|
| `publish-pages.ps1` | 打包 → 建公開 repo → push → 開 GitHub Pages → 等建置並驗證；`-DryRun` 只打包 |

## 快速啟動

```powershell
cd C:\node24\threejs-mech-taipei
python -m http.server 8099
# 瀏覽器開 http://127.0.0.1:8099/index.html
```

> **不要用 8080**：本機 8080 已被 java 服務佔用，`python -m http.server 8080` 會直接拋
> `PermissionError: [WinError 10013]`。若 8099 也被佔用，換一個沒人用的埠即可（例如 8787、5173）：
> `python -m http.server 8787`。查誰佔用：`netstat -ano | findstr :8080`。
>
> 一定要用 http server，不要直接雙擊 `index.html`（`file://` 會被 CORS 擋掉 ES module 與 GLB 載入）。
> 也可用 `live-server`（本機已安裝）：`live-server --port=8099`。
>
> 驗證腳本 `verify_smoke.py` 會自己起一個**隨機空閒埠**（`--port` 可指定固定埠），不需要先開 server，也不會撞到手上開著的頁面。

## 操作

| 桌機 | 動作 |
| :--- | :--- |
| `W` `A` `S` `D` | 前後左右移動（相對攝影機方向） |
| `Shift` | 加速（9 → 19 m/s） |
| 滑鼠移動 | 轉視角（需先點擊畫面鎖定滑鼠） |
| `R` | 重置整局 |

| 手機／平板（H5） | 動作 |
| :--- | :--- |
| 輕觸畫面 | 開始（不需滑鼠鎖定） |
| 左下圓形搖桿 | 拖曳移動，**類比**：輕推慢走、推到底 = 加速 |
| 右側空白處拖曳 | 左右轉視角、上下改變俯角 |
| 重新整理網頁 | 重置（手機沒有 `R` 鍵） |

## 手機 / H5

同一個 `index.html`，偵測到觸控裝置（`pointer: coarse` 或 `hover: none` + 多點觸控）就自動切換：

- 顯示虛擬搖桿、隱藏十字準星與鍵盤說明，開始鈕改為「輕觸畫面開始」。
- `viewport-fit=cover` + `env(safe-area-inset-*)`，避開 iPhone 瀏海／手勢區。
- `touch-action: none`、鎖掉 pinch／雙擊縮放、拖曳不捲動頁面。
- **效能**：像素比上限 1.6（桌機 2）、陰影貼圖 1024（桌機 2048）、
  粉塵 50／碎石 8（桌機 90／14）、寬度 < 640px 時 FOV 68、直式把鏡頭拉遠 1.18 倍。
- **PWA**：`manifest.webmanifest`（`display: fullscreen`、主題色、192/512 圖示），
  可「加到主畫面」全螢幕玩；`apple-touch-icon`、`theme-color`、`apple-mobile-web-app-*` 都已設。

### 用手機實際測（同一個 Wi-Fi）

```powershell
cd C:\node24\threejs-mech-taipei
python -m http.server 8099        # 預設綁 0.0.0.0，不只 localhost
ipconfig | findstr /i "IPv4"     # 取得電腦區網 IP，例如 192.168.1.20
```

手機瀏覽器開 `http://192.168.1.20:8099/index.html`。
若連不上，多半是 **Windows 防火牆**擋掉 Python：第一次啟動時按「允許存取」，
或手動加規則（系統管理員 PowerShell）：

```powershell
New-NetFirewallRule -DisplayName "threejs-mech-taipei 8099" -Direction Inbound `
  -Protocol TCP -LocalPort 8099 -Action Allow
```

> 目前 **沒有** Service Worker，所以是「連線就能玩的 H5」，不是可完全離線的快取版；
> 要離線請另外加 SW，並把 Three.js 改成離線 vendored（見「已知限制」）。

### 區網還是不通？（公司 Wi-Fi 常見）

公司 Wi-Fi 通常有 **client isolation**（同網段裝置互看不到）或手機走不同 SSID/VLAN，
即使同一網段也連不到電腦。實測環境（`10.27.90.x`）就是這個情況。此時有兩條路：

**A. 走外網 URL（推薦：GitHub Pages）**

GitHub Pages 用 `https://<帳號>.github.io/<repo>/`，手機用 4G/5G 也能開（本機實測 github.io 可達）。
注意兩件事：

1. `AdanY-cool/node24` 是 **private** repo，免費方案無法開 Pages；把整個 repo 轉公開會連 3,092 個內部
   測試檔一起曝光——**不要這樣做**。
2. 正確做法：**另開一個只含遊戲的公開 repo**（例如 `mech-taipei-h5`）。

一條命令全自動（建 repo → push → 開 Pages → 等建置 → 實際抓一次 index.html）：

```powershell
# 1) 把目標帳號的 PAT 放到 repo 外的檔案（一行，不會被 autopilot 收進版控）
#    %LOCALAPPDATA%\mech-taipei-tunnel\gh-token.txt
#    classic token 至少勾 public_repo；fine-grained 需 Administration/Contents/Pages: Read+Write

# 2) 發佈（Owner 換成你的帳號）
.\publish-pages.ps1 -Owner bodhi16889 -Repo mech-taipei-h5

# 只看要上傳哪些檔（不碰網路）
.\publish-pages.ps1 -DryRun
```

打包只收 `index.html`、`manifest.webmanifest`、`assets/`（icons + models/README.md）、`README.md`、
`verify_smoke.py`、`tunnel.ps1`、`.nojekyll`——**不含** `artifacts/` 截圖與 node24 其他內容。
腳本會先拿 token 打 `GET /user` 驗身分，帳號不符就直接停止（不會誤推到錯的帳號）。

部署後用同一支驗證腳本對準 Pages 網址跑一遍（本機已對「子路徑」版型驗過）：

```powershell
python verify_smoke.py --base-url https://<帳號>.github.io/mech-taipei-h5/index.html
```

> 本機已驗證：把打包結果放在子資料夾（模擬 `/mech-taipei-h5/`）下，`index.html` / `manifest.webmanifest` /
> `assets/icon-192.png` 全部 200，桌機＋手機整套 smoke test PASS——所有路徑都是相對路徑，可直接上 Pages。

**B. 不靠外網：讓手機直接連電腦**

- Windows 設定 → 網路與網際網路 → **行動熱點**：開啟後手機會拿到 `192.168.137.x`，
  開 `http://192.168.137.1:8099/index.html`（PC 上 `ipconfig` 看「行動熱點」那張網卡的 IPv4）。
  自己開的熱點沒有 client isolation，這招在辦公室最穩。
- 或用 **USB 網路共用**（手機開 USB tethering）：手機會變成 `192.168.42.129`，
  PC 拿到 `192.168.42.x`，手機瀏覽器開 `http://192.168.42.<PC>:8099/index.html`。

### Cloudflare Quick Tunnel（本網路不可用，保留備用）

```powershell
.\tunnel.ps1              # 自動下載 cloudflared、起 server + tunnel、印出 https://xxx.trycloudflare.com
.\tunnel.ps1 -Status     # 看網址／PID
.\tunnel.ps1 -Stop       # 停止
```

雲端 tunnel 需要能連 Cloudflare 邊緣的 **TCP/UDP 7844**。本機實測結果：

| 測試 | 結果 |
| :--- | :--- |
| `198.41.200.73:7844`（cloudflared 邊緣） | **timeout**（被擋）|
| `cloudflared --protocol http2` | 仍舊 dial `tcp :7844` timeout |
| pinggy（`ssh -p 443`） | 可建立，但 `*.pinggy.net` TLS 被 reset |
| `localtunnel.me` | timeout |
| `api.github.com` / `github.io` / `registry.npmjs.org` | 可達 |

所以 `tunnel.ps1` 已加上**前置檢查**：7844 不通就先警告（不再默默轉 5 分鐘）。
若換到別的網路（例如手機熱點分享網路給電腦）就可能會成功。


## 場景內容

- **地面**：600×600 平面 + 網格 + 四條街道路面。
- **大樓（8 棟，全方塊）**：台北 101（9 段堆疊塔身 + 塔尖）、新光三越、國泰置地廣場、台北車站、
  南港展覽館、富邦人壽大樓、信義誠品、北門郵局。清單在 `index.html` 的 `CITY` 陣列。
- **機甲**：軀幹／駕駛艙（自發光）／肩甲／手臂／雙腿方塊組成，走路時腿部擺動、身體微幅上下。
- **窗戶貼圖**：`makeFacadeTexture()` 用 canvas 隨機點亮窗格，避免大樓看起來是一片死灰。
- **碰撞判定**：機甲外框（半徑 1.35）vs 大樓 AABB（`Box3` 取的半高、半寬）。
- **倒塌**：以「建築朝倒塌方向的底座邊」為轉軸（`Object3D.attach` 到 pivot），
  以重力感的 `k²` 曲線轉到約 87°，落地時噴碎石（受重力、會彈跳）＋粉塵（Points）。
- **記帳**：每棟 5,000 萬（`CONFIG.cost = 50_000_000`），右上角累計金額＋最近 6 筆紀錄，
  撞擊瞬間中間另有大字 `−5,000 萬 · <大樓名>`。

## 程式結構（都在 `index.html`）

| 區塊 | 內容 |
| :--- | :--- |
| 1. 設定 | `CONFIG`（速度、相機、費用、模型路徑）、`CITY`（大樓清單）、`SPAWN` |
| 2–3. Renderer / Scene | WebGL renderer、陰影、ACES tone mapping、半球光＋主光＋環境光 |
| 4. 地面 | 平面、`GridHelper`、街道路面 |
| 5–6. 大樓 | `makeFacadeTexture` / `makeFacadeMaterial` / `makeBoxBuilding` / `makeTower101`、`spawnBuildings` |
| 7. 機甲 | `buildMechBlockout()`（可被 GLB 取代的 `mechParts` 子群組） |
| 8. 模型載入 | `tryLoadGLB` / `fitToGround` / `applyModelOverrides` |
| 9. 倒塌 | `collapseBuilding` / `updateCollapses` / `spawnDust` / `spawnChunks` / `updateDebris` |
| 10. HUD | `recordDeduction`（累計金額、紀錄、閃字） |
| 11. 輸入 | 鍵盤、Pointer Lock 滑鼠、**虛擬搖桿（Pointer Events）**、**拖曳轉視角**、`start()` |
| 12. 更新迴圈 | `updatePlayer`（鍵盤與搖桿合流、類比加速）/ `resolveCollisions` / `updateCamera` / `animate` |
| 13. 啟動 | `spawnBuildings()`、`applyModelOverrides()`、`window.__game` 除錯鉤子 |

`IS_COARSE` 在檔案開頭決定觸控模式（掛 `html.touch` class、像素比、陰影尺寸、粒子量、FOV）。
`animate()` 用兩個時間步長：位移用 `dt ≤ 0.1`（低幀率手機不至於變慢；單幀最大位移 1.9m，
遠小於大樓寬度，不會穿模），倒塌／碎石動畫用 `animDt ≤ 0.25`，倒塌時長仍接近 1.75 秒。

## 驗證（可重跑）

```powershell
python verify_smoke.py           # headless Chromium（Playwright）+ 自動選埠的本機 http server
python verify_smoke.py --headed  # 想親眼看它撞
python verify_smoke.py --port 8099  # 指定固定埠
python verify_smoke.py --base-url https://xxx.trycloudflare.com/index.html  # 改測既有網址（tunnel／Pages／區網 IP）
```

檢查項目（桌機）：render loop 有跑、8 棟大樓生成、`W` 真的把機甲往前推、加速撞上台北 101 後
`state.destroyed == 1`、`state.totalCost == 50,000,000`、HUD 文字含「扣除 5,000 萬建造費」、
倒塌後 pivot 轉到約 87°、沒有 console error（`assets/models/*.glb` 的 404 屬預期 fallback，已排除），
存 `artifacts/smoke-city.png`、`artifacts/smoke-collapse.png`。

檢查項目（手機 / H5）：用 Playwright 的 **Pixel 5 裝置描述**（觸控、393×851、DPR 2.75）跑：
偵測成觸控裝置、搖桿可見、`tap` 開始、CDP 送真觸控事件拖曳右側 → `look.yaw` 改變、
搖桿推到底 → 機甲前進（`stick.y > 0.8`）並撞倒台北 101 扣 5,000 萬、放手後搖桿歸零、
沒有 console error，存 `artifacts/smoke-mobile.png`、`artifacts/smoke-mobile-collapse.png`。

最近一次結果：

```
[PASS] render loop advances — 7 -> 29 frames in 1s
[PASS] city spawned — {'buildings': 8, 'alive': 8}
[PASS] W moves mech forward (-Z) — z 22.00 -> 18.15
[PASS] collision collapses a building — {'destroyed': 1, 'name': '台北 101', ...}
[PASS] deduction booked (5,000 萬) — NT$ 50,000,000
[PASS] HUD shows 扣除 5,000 萬建造費
[PASS] HUD total shows 5,000 萬
[PASS] collapse animation tilts the tower flat — 1.52 rad (~87°)
[PASS] no console errors / screenshot captured
--- mobile (Pixel 5, touch) ---
[PASS] mobile detected as touch device — viewport 393x727
[PASS] virtual joystick visible — display=block
[PASS] tap starts the game
[PASS] drag rotates camera — yaw 0.00 -> 0.43
[PASS] joystick moves mech forward — z 22.0 -> 1.2, stick={'x': 0, 'y': 1}
[PASS] mobile collision collapses + deducts — NT$ 50,000,000
[PASS] mobile HUD records 扣除 5,000 萬建造費
[PASS] joystick resets on release
[PASS] no console errors (mobile) / mobile screenshot captured
RESULT: PASS
```

## 換成 Tripo3D 模型（階段 2）

程式已經寫好載入與正規化流程，**只要把檔案放進去就會自動替換**；檔案不存在時會靜默沿用方塊版。

1. 在 [Tripo3D](https://www.tripo3d.ai/) 生成／匯出 **GLB**（建議：Y-up、正面朝 `-Z`、
   貼圖內嵌、面數壓在 3 萬以下），下載後改名成：
   - `assets/models/mech.glb` → 機甲（自動縮到 `CONFIG.models.mechTargetHeight = 4.2` 高、置中、貼地）
   - `assets/models/taipei101.glb` → 台北 101（自動縮到原方塊塔同高）
2. 重新整理頁面即可。Console 會印 `[models] 已套用機甲 GLB：...`。
3. 要換其他地標：在 `CITY` 加一筆（`id / name / kind / x / z / w / d / h`），
   並在 `CONFIG.models.buildings` 加上 `id: 'assets/models/xxx.glb'`。
4. 想一次關掉模型載入：`CONFIG.models.enabled = false`。
5. 高度／朝向不合：改 `fitToGround()`（縮放、置中、貼地）或 `CONFIG.models.mechTargetHeight`；
   模型若正面不是 `-Z`，在 GLB 端先轉正，或在載入後補 `model.rotation.y`。

目前 `assets/models/` 只有說明檔，所以跑起來是方塊版。

## 已知限制

- 碰撞是 **AABB**（軸對齊），不支援斜放建築；倒塌後的大樓不再具碰撞。
- 大樓倒塌是「整棟繞底座邊翻倒」，沒有逐層碎裂的物理模擬。
- 手機效能：低階機仍可能掉到 20–30 fps（Three.js + 陰影）。真要再省，把 `CONFIG.models.enabled = false`、
  `renderer.shadowMap.enabled = false`、`IS_COARSE` 的像素比降到 1.2，或把 `CITY` 減成 4 棟。
- 沒有 Service Worker；Three.js 仍由 CDN（jsDelivr，`three@0.160.0`）載入。要完全離線請 `npm i three@0.160.0`，
  把 `build/` 與 `examples/jsm/` 複製到 `vendor/three/`，並改 `index.html` 的 importmap：

  ```json
  { "imports": { "three": "./vendor/three/build/three.module.js",
                 "three/addons/": "./vendor/three/examples/jsm/" } }
  ```
