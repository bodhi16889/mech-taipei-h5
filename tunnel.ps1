#!/usr/bin/env pwsh
<#
.SYNOPSIS
    用 Cloudflare Quick Tunnel 把本機的 threejs-mech-taipei 變成公開 https 網址，手機（4G/5G 也行）可直接開。
.DESCRIPTION
    會做三件事：起本機靜態 server（只綁 127.0.0.1）→ 起 cloudflared quick tunnel → 印出 https://xxx.trycloudflare.com。
    不會推任何程式碼到 GitHub；cloudflared 首次會自動下載到 %LOCALAPPDATA%\cloudflared\。
    每次重開網址都會變，電腦關機／關掉 tunnel 就失效。
.EXAMPLE
    .\tunnel.ps1              # 啟動並印出公開網址
    .\tunnel.ps1 -Status     # 看目前網址／是否還在跑
    .\tunnel.ps1 -Stop       # 停止 tunnel 與本機 server
#>
param(
    [switch]$Status,
    [switch]$Stop,
    [int]$Port = 8123
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$stateDir = Join-Path $env:LOCALAPPDATA 'mech-taipei-tunnel'
$stateFile = Join-Path $stateDir 'state.json'
$cfExe = Join-Path $env:LOCALAPPDATA 'cloudflared\cloudflared.exe'
$logFile = Join-Path $stateDir 'cloudflared.log'
$serverLog = Join-Path $stateDir 'server.log'

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

function Get-State {
    if (Test-Path $stateFile) { return Get-Content $stateFile -Raw | ConvertFrom-Json }
    return $null
}

function Stop-All($state) {
    if (-not $state) { return }
    foreach ($procId in @($state.TunnelPid, $state.ServerPid)) {
        if ($procId) {
            Get-Process -Id $procId -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host ("停止 PID {0} ({1})" -f $_.Id, $_.ProcessName)
                Stop-Process -Id $_.Id -Force
            }
        }
    }
    Remove-Item $stateFile -ErrorAction SilentlyContinue
}

function Test-Cloudflared {
    if (Test-Path $cfExe) { return }
    Write-Host '找不到 cloudflared，下載中（約 60 MB，只做一次）...'
    $dir = Split-Path $cfExe -Parent
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $url = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'
    Invoke-WebRequest -Uri $url -OutFile $cfExe -UseBasicParsing
    Write-Host ("已下載 {0} ({1:N1} MB)" -f $cfExe, ((Get-Item $cfExe).Length / 1MB))
}

# ---------- -Stop ----------
if ($Stop) {
    $state = Get-State
    if (-not $state) { Write-Host '沒有進行中的 tunnel（找不到 state）。' }
    else { Stop-All $state; Write-Host '已停止。' }
    return
}

# ---------- -Status ----------
if ($Status) {
    $state = Get-State
    if (-not $state) { Write-Host '目前沒有 tunnel。用 .\tunnel.ps1 啟動。'; return }
    $tunnelAlive = $state.TunnelPid -and (Get-Process -Id $state.TunnelPid -ErrorAction SilentlyContinue)
    $serverAlive = $state.ServerPid -and (Get-Process -Id $state.ServerPid -ErrorAction SilentlyContinue)
    Write-Host ("網址     : {0}" -f $state.Url)
    Write-Host ("本機     : http://127.0.0.1:{0}/index.html" -f $state.Port)
    Write-Host ("tunnel   : {0} (PID {1})" -f $(if ($tunnelAlive) { '執行中' } else { '已停止' }), $state.TunnelPid)
    Write-Host ("server   : {0} (PID {1})" -f $(if ($serverAlive) { '執行中' } else { '已停止' }), $state.ServerPid)
    return
}

# ---------- 啟動 ----------
$old = Get-State
if ($old) { Write-Host '先清掉上一組 tunnel/server。'; Stop-All $old }

Test-Cloudflared

# 0) 先驗外網能不能到 Cloudflare tunnel 邊緣（TCP 7844）。
#    公司網路常整段擋掉 7844，cloudflared 只會一直「Retrying connection」而不报錯，先驗比較快。
function Test-EdgePort {
    param([string]$HostName = '198.41.200.73', [int]$PortNum = 7844, [int]$TimeoutMs = 4000)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($HostName, $PortNum)
        if (-not $task.Wait($TimeoutMs)) { return $false }
        return $client.Connected
    } catch { return $false } finally { $client.Dispose() }
}

if (-not (Test-EdgePort)) {
    Write-Warning '外網到 Cloudflare tunnel 邊緣（TCP 7844）不通：這個網路擋掉了 cloudflared 的通道。'
    Write-Warning '雲端 tunnel 在此網路不可用；替代方式：① 同一 Wi-Fi 區網 IP、② 電腦開行動熱點讓手機直連、③ GitHub Pages。'
    Write-Warning '仍要嘗試的話會繼續（例如改用手機熱點分享網路給電腦）。'
}

# 1) 本機靜態 server（只綁 127.0.0.1，對外由 tunnel 代理）
$server = Start-Process -FilePath 'python' `
    -ArgumentList '-m', 'http.server', $Port, '--bind', '127.0.0.1' `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $serverLog -RedirectStandardError "$serverLog.err"
Start-Sleep -Seconds 2
if (-not (Get-Process -Id $server.Id -ErrorAction SilentlyContinue)) {
    throw "本機 server 起不來（port $Port 可能被佔用）。換一個：.\tunnel.ps1 -Port 8124"
}
Write-Host ("本機 server OK：http://127.0.0.1:{0}/index.html" -f $Port)

# 2) cloudflared quick tunnel
#    公司網路常擋 outbound UDP 7844（QUIC），所以固定用 --protocol http2（TCP 443），成功率最高。
if (Test-Path $logFile) { Remove-Item $logFile -Force }
$tunnel = Start-Process -FilePath $cfExe `
    -ArgumentList 'tunnel', '--url', "http://127.0.0.1:$Port", '--no-autoupdate', '--protocol', 'http2', '--logfile', $logFile `
    -WindowStyle Hidden -PassThru

$url = $null
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Path $logFile) {
        $m = Select-String -Path $logFile -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches |
             ForEach-Object { $_.Matches } | Select-Object -First 1
        if ($m) { $url = $m.Value; break }
    }
    if (-not (Get-Process -Id $tunnel.Id -ErrorAction SilentlyContinue)) { break }
}

# 拿到網址不代表 tunnel 已連上：真的從外網抓一次 index.html 才算成功
$publicOk = $false
if ($url) {
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri "$url/index.html" -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -eq 200 -and $r.Content -match '機甲拆除') { $publicOk = $true; break }
        } catch { }
    }
}

if (-not $url) {
    Write-Warning "拿不到 trycloudflare 網址，log 最後幾行："
    if (Test-Path $logFile) { Get-Content $logFile -Tail 15 }
    Write-Warning '（若被公司網路/Proxy 擋住，cloudflared 需要能連 outbound TCP 443）'
} elseif (-not $publicOk) {
    Write-Warning "拿到網址但外網還連不到（tunnel 尚未連上 Cloudflare 邊緣）：$url"
    Write-Warning "log 最後幾行（若出現 quic timeout，改跑 .\tunnel.ps1 -Protocol quic 或換網路）："
    if (Test-Path $logFile) { Get-Content $logFile -Tail 10 }
} else {
    @{
        Url       = $url
        Port      = $Port
        TunnelPid = $tunnel.Id
        ServerPid = $server.Id
        StartedAt = (Get-Date).ToString('s')
    } | ConvertTo-Json | Set-Content -Path $stateFile -Encoding UTF8
}

Write-Host ''
Write-Host '=================================================='
if ($url -and $publicOk) {
    Write-Host (" 手機請開： {0}/index.html" -f $url) -ForegroundColor Green
} elseif ($url) {
    Write-Host (" 網址已產生但尚未接通： {0}/index.html" -f $url) -ForegroundColor Yellow
} else {
    Write-Host ' tunnel 沒有成功取得網址' -ForegroundColor Yellow
}
Write-Host (" 本機測試： http://127.0.0.1:{0}/index.html" -f $Port)
Write-Host ' 停止：     .\tunnel.ps1 -Stop'
Write-Host '=================================================='
