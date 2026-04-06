# Barretão Watchdog — reinicia hub e tunnel automaticamente
$d = "c:\Users\Administrador\Desktop\Barretão"
if ($MyInvocation.MyCommand.Path) {
    $d = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$python  = "$d\.venv311\Scripts\python.exe"
$hubpy   = "$d\barretao_hub.py"
$cfgYml  = "C:\Users\Administrador\.cloudflared\config.yml"

function Is-PortListening($port) {
    return ($null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue))
}

function Is-TunnelAlive {
    $info = cloudflared tunnel info barretao 2>&1 | Out-String
    return ($info -match "CONNECTOR ID")
}

$hubProc    = $null
$tunnelProc = $null

while ($true) {
    # ── Hub ──────────────────────────────────────────────────────────────
    if (-not (Is-PortListening 8787)) {
        Write-Host "[$(Get-Date -f 'HH:mm:ss')] Hub offline — reiniciando..."
        if ($hubProc -and -not $hubProc.HasExited) { $hubProc.Kill() }
        $hubProc = Start-Process -FilePath $python -ArgumentList "`"$hubpy`"" `
                     -WorkingDirectory $d -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 4
    }

    # ── Tunnel ───────────────────────────────────────────────────────────
    if (-not (Is-TunnelAlive)) {
        Write-Host "[$(Get-Date -f 'HH:mm:ss')] Tunnel offline — reiniciando..."
        Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 2
        $tunnelProc = Start-Process -FilePath "cloudflared.exe" `
                        -ArgumentList "tunnel --config `"$cfgYml`" run barretao" `
                        -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 8
    }

    Start-Sleep -Seconds 30
}
