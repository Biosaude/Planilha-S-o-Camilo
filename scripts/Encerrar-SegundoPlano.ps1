$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pidFile = Join-Path $root 'data\runtime\streamlit.pid'
if (-not (Test-Path $pidFile)) { exit 0 }
$serverId = 0
[void][int]::TryParse((Get-Content $pidFile -Raw).Trim(), [ref]$serverId)
if ($serverId -gt 0) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverId" -ErrorAction SilentlyContinue
    if ($process -and $process.Name -like 'pythonw*' -and $process.CommandLine -like '*streamlit*' -and $process.CommandLine -like '*app.py*') {
        Stop-Process -Id $serverId -ErrorAction Stop
    }
}
Remove-Item $pidFile -Force
