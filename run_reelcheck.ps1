# ReelCheck supervisor: keeps the server + Cloudflare tunnel alive.
# Checks every 30s; restarts either one if it has died. Runs at logon via a
# Scheduled Task (see install_autostart — created by Claude). Logs to logs\supervisor.txt
$ErrorActionPreference = "SilentlyContinue"
$dir = "C:\Projects\reel-verification"
# Use the real Python directly (not the Windows Store "python.exe" alias stub).
$python = "C:\Users\HP\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if (-not (Test-Path $python)) { $python = "python" }
Set-Location $dir
New-Item -ItemType Directory -Force -Path "$dir\logs" | Out-Null

function Log($m) { "$((Get-Date).ToString('s'))  $m" | Add-Content "$dir\logs\supervisor.txt" }
Log "supervisor started"

while ($true) {
    # 1) API server on :8000 — check the port is LISTENING (not an HTTP response,
    #    which stalls for 20-40s during a verify and would cause false restarts).
    $ok = $false
    try { $ok = [bool](Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) } catch {}
    if (-not $ok) {
        Log "server down -> restarting"
        Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList "main.py" -WorkingDirectory $dir `
            -RedirectStandardError "$dir\logs\srv_err.txt" -RedirectStandardOutput "$dir\logs\srv_out.txt"
    }

    # 2) Cloudflare tunnel
    if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
        Log "tunnel down -> restarting"
        Start-Process -WindowStyle Hidden -FilePath "$dir\cloudflared.exe" -ArgumentList "tunnel","run","reelcheck" `
            -RedirectStandardError "$dir\logs\cf_tunnel.txt" -RedirectStandardOutput "$dir\logs\cf_tunnel_out.txt"
    }

    Start-Sleep -Seconds 30
}
