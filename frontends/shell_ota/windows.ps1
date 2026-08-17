# Shell OTA helper — Windows PowerShell. Arg: manifest.json path.
param([Parameter(Mandatory = $true)][string]$ManifestPath)
$ErrorActionPreference = 'Stop'
$m = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$log = if ($m.logFile) { [string]$m.logFile } else { Join-Path $env:TEMP 'ga-shell-ota.log' }
function Log([string]$x) {
    Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $x)
}
Log 'start'
$lock = if ($m.lockFile) { [string]$m.lockFile } else { Join-Path $env:TEMP 'ga-shell-ota.lock' }
if (Test-Path -LiteralPath $lock) {
    $op = Get-Content -LiteralPath $lock -ErrorAction SilentlyContinue
    if ($op -and (Get-Process -Id $op -ErrorAction SilentlyContinue)) {
        Log "lock held $op"; exit 1
    }
}
$PID | Set-Content -LiteralPath $lock
try {
    $shellPid = [int]$m.pid
    if ($shellPid -gt 0) {
        for ($i = 0; $i -lt 120; $i++) {
            if (-not (Get-Process -Id $shellPid -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 500
        }
        if (Get-Process -Id $shellPid -ErrorAction SilentlyContinue) { throw 'shell still alive' }
    }
    $bridgePid = [int]$m.bridgePid
    if ($bridgePid -gt 0) {
        for ($i = 0; $i -lt 60; $i++) {
            if (-not (Get-Process -Id $bridgePid -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 300
        }
    }

    function Free-Port([int]$port) {
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 400
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "port $port busy"
        }
    }
    Free-Port ([int]$m.bridgePort)
    Free-Port 19736
    Free-Port 19737

    $liveApp = [string]$m.liveApp
    $liveRt = [string]$m.liveRuntimeApp
    $newShell = [string]$m.newShell
    $newRt = [string]$m.newRuntimeApp
    $protDir = Join-Path ([string]$m.workDir) 'prot'
    New-Item -ItemType Directory -Force -Path $protDir | Out-Null
    $hashes = @{}
    $protected = @($m.protected)

    function Test-Protected([string]$rel) {
        foreach ($p in $protected) {
            if ($p.EndsWith('/')) {
                $b = $p.TrimEnd('/')
                if ($rel -eq $b -or $rel.StartsWith("$b/")) { return $true }
            } elseif ($rel -eq $p) { return $true }
        }
        return $false
    }

    foreach ($name in $protected) {
        $base = $name.TrimEnd('/')
        $src = Join-Path $liveRt $base
        if (-not (Test-Path -LiteralPath $src)) { continue }
        $dst = Join-Path $protDir $base
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        $item = Get-Item -LiteralPath $src
        if ($item -is [IO.FileInfo]) {
            $hashes[$base] = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        try {
            Move-Item -LiteralPath $src -Destination $dst -Force
            Log "snap mv $base"
        } catch {
            Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
            Remove-Item -LiteralPath $src -Recurse -Force
            Log "snap copy $base"
        }
    }

    $bak = "$liveApp.ota-bak"
    if (Test-Path -LiteralPath $bak) { Remove-Item -LiteralPath $bak -Force }
    $okMove = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            Move-Item -LiteralPath $liveApp -Destination $bak -Force
            $okMove = $true
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $okMove) { throw 'cannot move live exe' }
    Copy-Item -LiteralPath $newShell -Destination $liveApp -Force

    if ($newRt -and (Test-Path -LiteralPath $newRt)) {
        Get-ChildItem -LiteralPath $newRt -Recurse -File -Force | ForEach-Object {
            $rel = $_.FullName.Substring($newRt.Length).TrimStart('\').Replace('\', '/')
            if (Test-Protected $rel) { return }
            $dest = Join-Path $liveRt ($rel -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
        }
        Log 'overlay runtime'
    }

    foreach ($name in $protected) {
        $base = $name.TrimEnd('/')
        $src = Join-Path $protDir $base
        if (-not (Test-Path -LiteralPath $src)) { continue }
        $dst = Join-Path $liveRt $base
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
        try { Move-Item -LiteralPath $src -Destination $dst -Force }
        catch { Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force }
        Log "restore $base"
    }

    foreach ($k in $hashes.Keys) {
        $f = Join-Path $liveRt $k
        if (-not (Test-Path -LiteralPath $f)) { throw "missing $k" }
        $got = (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($got -ne $hashes[$k]) { throw "hash mismatch $k" }
    }

    $sv = Join-Path (Split-Path $liveRt) 'SHELL_VERSION'
    Set-Content -LiteralPath $sv -Value ([string]$m.version)

    Start-Process -FilePath $liveApp
    $ok = $false
    $old = [string]$m.oldBuildId
    $port = [int]$m.bridgePort
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $body = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/identity" -f $port) -TimeoutSec 2
            if ($old) {
                if ($body.build_id -and $body.build_id -ne $old) { $ok = $true; break }
            } else { $ok = $true; break }
        } catch {}
    }
    if (-not $ok) { throw 'identity check failed' }
    if (Test-Path -LiteralPath $bak) { Remove-Item -LiteralPath $bak -Force }
    Log 'OK'
    exit 0
} catch {
    Log ("FAIL " + $_.Exception.Message)
    try {
        $bak = ([string]$m.liveApp) + '.ota-bak'
        if (Test-Path -LiteralPath $bak) {
            if (Test-Path -LiteralPath ([string]$m.liveApp)) {
                Remove-Item -LiteralPath ([string]$m.liveApp) -Force
            }
            Move-Item -LiteralPath $bak -Destination ([string]$m.liveApp) -Force
            Start-Process -FilePath ([string]$m.liveApp)
        }
    } catch {}
    exit 1
} finally {
    Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
}
