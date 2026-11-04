#!/usr/bin/env pwsh
<#
.SYNOPSIS
    把 threejs-mech-taipei 發佈成 GitHub Pages（公開 repo，只含遊戲檔案），給手機一個固定 https 網址。
.DESCRIPTION
    流程：打包 dist（排除 artifacts）→ 驗證 token 身分 → 建 repo（若不存在）→ push main
          → 開 Pages（API）→ 等 Pages 建置完成並實際抓一次 index.html → 印出網址。
    token 只從參數／檔案／環境變數進來，不會寫入任何檔案、也不會印在輸出。
.EXAMPLE
    # 1) 把 bodhi16889 的 PAT 放到 repo 外的檔案（避免被 autopilot 收進版控）
    #    %LOCALAPPDATA%\mech-taipei-tunnel\gh-token.txt   ← 只有一行 token
    .\publish-pages.ps1 -Owner bodhi16889 -Repo mech-taipei-h5
.EXAMPLE
    .\publish-pages.ps1 -DryRun          # 只打包並列出要上傳的檔案，不碰網路
#>
param(
    [string]$Token = '',
    [string]$TokenFile = (Join-Path $env:LOCALAPPDATA 'mech-taipei-tunnel\gh-token.txt'),
    [string]$Owner = 'bodhi16889',
    [string]$Repo = 'mech-taipei-h5',
    [string]$Branch = 'main',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$dist = Join-Path $env:TEMP 'mech-taipei-h5'

$ApiBase = 'https://api.github.com'
$Headers = @{ 'User-Agent' = 'mech-taipei-publish'; 'Accept' = 'application/vnd.github+json' }

# ---------- 1. 打包 ----------
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $dist 'assets\models') | Out-Null

$files = @('index.html', 'manifest.webmanifest', 'README.md', 'verify_smoke.py', 'verify_models.py',
           'tripo.py', 'tripo_selftest.py', 'tunnel.ps1', 'publish-pages.ps1')
foreach ($f in $files) {
    $src = Join-Path $root $f
    if (-not (Test-Path $src)) { throw "缺少必要檔案：$src" }
    Copy-Item $src -Destination $dist
}
Copy-Item (Join-Path $root 'assets\*.png') -Destination (Join-Path $dist 'assets')
Copy-Item (Join-Path $root 'assets\models\README.md') -Destination (Join-Path $dist 'assets\models')

# Pages 不需要 Jekyll；避免任何底線開頭檔案被吃掉
New-Item -ItemType File -Force -Path (Join-Path $dist '.nojekyll') | Out-Null

$bundle = Get-ChildItem $dist -Recurse -File
$totalKb = [math]::Round(($bundle | Measure-Object Length -Sum).Sum / 1KB, 1)
Write-Host ("打包完成：{0} 個檔案，{1} KB → {2}" -f $bundle.Count, $totalKb, $dist)
$bundle | ForEach-Object { Write-Host ("  - {0}" -f $_.FullName.Substring($dist.Length + 1)) }

if ($DryRun) {
    Write-Host ''
    Write-Host '（-DryRun：不建立 repo、不 push、不開 Pages）'
    exit 0
}

# ---------- 2. token ----------
if (-not $Token) {
    if (Test-Path $TokenFile) { $Token = (Get-Content $TokenFile -Raw).Trim() }
    elseif ($env:GH_TOKEN_BODHI) { $Token = $env:GH_TOKEN_BODHI.Trim() }
}
if (-not $Token) {
    throw @"
找不到 token。請用擁有 $Owner 權限的 Personal Access Token（classic，至少勾 public_repo；fine-grained 需 Administration: Read+Write + Contents: Read+Write + Pages: Read+Write）。

建立後只放一行到（repo 外，不會被 autopilot 收進版控）：
  $TokenFile

或：
  `$env:GH_TOKEN_BODHI = 'ghp_xxx'; .\publish-pages.ps1
"@
}
$Headers['Authorization'] = "token $Token"

function Api([string]$Method, [string]$Path, $Body) {
    $req = @{ Method = $Method; Uri = "$ApiBase$Path"; Headers = $Headers }
    if ($null -ne $Body) {
        # PS 5.1 的 Invoke-RestMethod 會用非 UTF-8 編碼送字串，導致中文 JSON 壞掉
        # （GitHub 回 400 Problems parsing JSON）；改成自己送 UTF-8 bytes。
        $json = $Body | ConvertTo-Json -Depth 6 -Compress
        $req['Body'] = [System.Text.Encoding]::UTF8.GetBytes($json)
        $req['ContentType'] = 'application/json; charset=utf-8'
    }
    try {
        return Invoke-RestMethod @req
    } catch {
        $resp = $_.Exception.Response
        if ($resp) {
            $code = [int]$resp.StatusCode
            return [pscustomobject]@{ __status = $code; __error = $_.ErrorDetails.Message }
        }
        throw
    }
}

$me = Api 'GET' '/user' $null
if ($me.__status) { throw "token 無效（HTTP $($me.__status)）：$($me.__error)" }
if ($me.login -ne $Owner) {
    throw "這個 token 屬於「$($me.login)」，不是「$Owner」。請改用 $Owner 自己的 PAT（或把 -Owner 改成 $($me.login)）。"
}
Write-Host "token 身分確認：$($me.login) ✔"

# ---------- 3. 建立 repo ----------
$existing = Api 'GET' "/repos/$Owner/$Repo" $null
$repoEmpty = $true
if ($existing.__status -eq 404) {
    Write-Host "建立公開 repo：$Owner/$Repo ..."
    $created = Api 'POST' '/user/repos' @{
        name        = $Repo
        description = '台北機甲拆除模擬器 · Three.js H5（WASD / 手機虛擬搖桿）'
        homepage    = "https://$Owner.github.io/$Repo/"
        private     = $false
        has_issues  = $true
        has_wiki    = $false
    }
    if ($created.__status) { throw "建立 repo 失敗（HTTP $($created.__status)）：$($created.__error)" }
} else {
    Write-Host "repo 已存在：$($existing.full_name)（visibility=$($existing.visibility)）"
    # 用「遠端分支是否存在」判斷空 repo（空的 repo 沒有 main 分支，API 回 404）
    $br = Api 'GET' "/repos/$Owner/$Repo/branches/$Branch" $null
    if (-not $br.__status) { $repoEmpty = $false }
}

# ---------- 4. push（保留遠端歷史，不強推）----------
Push-Location $dist
try {
    # git 會把進度寫到 stderr；在 $ErrorActionPreference='Stop' 下會被當成終止錯誤，所以這裡改 Continue
    $ErrorActionPreference = 'Continue'
    git init -b $Branch | Out-Null
    git config user.name  'mech-taipei-publisher'
    git config user.email "$Owner@users.noreply.github.com"
    git remote add origin "https://github.com/$Owner/$Repo.git"

    # token 不放進命令列（避免出現在 log / process list），改走 git 設定環境變數
    $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$Token"))
    $env:GIT_CONFIG_COUNT = '1'
    $env:GIT_CONFIG_KEY_0 = 'http.extraheader'
    $env:GIT_CONFIG_VALUE_0 = "Authorization: Basic $b64"
    $env:GIT_TERMINAL_PROMPT = '0'

    if (-not $repoEmpty) {
        # 把 HEAD 接到遠端 main 上，再把它當父節點建立新 commit → 不用 --force 也不會蓋掉 GitHub 上的手動修改
        git fetch --depth 1 origin $Branch *> $null
        if ($LASTEXITCODE -eq 0) { git reset --mixed FETCH_HEAD *> $null }
    }

    git add -A
    $changed = (git status --porcelain)
    if ($changed) {
        git -c core.autocrlf=false commit -m "release: 台北機甲拆除模擬器 H5（Three.js）" *> $null
        if ($LASTEXITCODE -ne 0) { throw "git commit 失敗（exit $LASTEXITCODE）" }
    } else {
        Write-Host '內容與遠端相同，沒有新 commit。'
    }

    git push origin "HEAD:$Branch"
    if ($LASTEXITCODE -ne 0) { throw "git push 失敗（exit $LASTEXITCODE）" }

    $sha = (git rev-parse --short HEAD).Trim()
    Write-Host "push 完成：$Owner/$Repo@$sha"
} finally {
    $ErrorActionPreference = 'Stop'
    Remove-Item Env:GIT_CONFIG_COUNT, Env:GIT_CONFIG_KEY_0, Env:GIT_CONFIG_VALUE_0 -ErrorAction SilentlyContinue
    Pop-Location
}

# ---------- 5. 開 Pages ----------
$pages = Api 'GET' "/repos/$Owner/$Repo/pages" $null
if ($pages.__status -eq 404) {
    Write-Host '開啟 GitHub Pages（main / root）...'
    $enabled = Api 'POST' "/repos/$Owner/$Repo/pages" @{ source = @{ branch = $Branch; path = '/' } }
    if ($enabled.__status -and $enabled.__status -ne 409) {
        throw "開啟 Pages 失敗（HTTP $($enabled.__status)）：$($enabled.__error)"
    }
} else {
    Write-Host "Pages 已開啟：$($pages.html_url)"
}

# ---------- 6. 等建置 + 實際抓一次 ----------
$siteUrl = "https://$Owner.github.io/$Repo/index.html"
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 10
    $build = Api 'GET' "/repos/$Owner/$Repo/pages/builds/latest" $null
    $status = if ($build.__status) { "unknown" } else { $build.status }
    Write-Host ("  [{0,3}s] Pages build: {1}" -f (($i + 1) * 10), $status)
    if ($status -eq 'errored') { throw "Pages 建置失敗：$($build.error.message)" }
    try {
        $r = Invoke-WebRequest -Uri $siteUrl -UseBasicParsing -TimeoutSec 20
        if ($r.StatusCode -eq 200 -and $r.Content -match '機甲拆除') { $ok = $true; break }
    } catch { }
}

Write-Host ''
Write-Host '=================================================='
if ($ok) {
    Write-Host (" 手機請開： https://{0}.github.io/{1}/" -f $Owner, $Repo) -ForegroundColor Green
    Write-Host (" 驗證：   python verify_smoke.py --base-url {0}" -f $siteUrl)
} else {
    Write-Host ' Pages 還沒生效（通常再等 1–3 分鐘）。網址應為：' -ForegroundColor Yellow
    Write-Host (" https://{0}.github.io/{1}/" -f $Owner, $Repo)
}
Write-Host '=================================================='
