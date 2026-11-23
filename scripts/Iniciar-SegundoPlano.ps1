$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
$database = Join-Path $root 'data\tuss.sqlite3'
$stateDir = Join-Path $root 'data\runtime'
$pidFile = Join-Path $stateDir 'streamlit.pid'
$log = Join-Path $stateDir 'streamlit.log'
$errorLog = Join-Path $stateDir 'streamlit-error.log'
$url = 'http://127.0.0.1:8501'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
try {
    if (-not (Test-Path $pythonw)) { throw 'Python nao instalado. Execute o instalador primeiro.' }
    if (-not (Test-Path $database)) { throw 'Banco TUSS ausente. Importe a base antes de iniciar.' }
    if (Test-Path $pidFile) {
        $existingId = 0
        [void][int]::TryParse((Get-Content $pidFile -Raw).Trim(), [ref]$existingId)
        $existing = if ($existingId -gt 0) { Get-CimInstance Win32_Process -Filter "ProcessId=$existingId" -ErrorAction SilentlyContinue } else { $null }
        if ($existing -and $existing.Name -like 'pythonw*' -and $existing.CommandLine -like '*streamlit*' -and $existing.CommandLine -like '*app.py*') {
            Start-Process $url
            exit 0
        }
        Remove-Item $pidFile -Force
    }
    $env:BIOSAUDE_AUTH_MODE = 'public'
    $env:BIOSAUDE_TUSS_DB = $database
    $env:BIOSAUDE_AUDIT_DB = Join-Path $root 'data\audit.sqlite3'
    $arguments = @('-m','streamlit','run','app.py','--server.address','127.0.0.1','--server.port','8501','--server.headless','true')
    $process = Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $errorLog -PassThru
    Set-Content -Path $pidFile -Value $process.Id -Encoding ASCII
    $ready = $false
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) { break }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/_stcore/health' -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) { throw 'O servidor nao respondeu. Consulte o arquivo de erros em data\runtime.' }
    Start-Process $url
} catch {
    Add-Content -Path (Join-Path $stateDir 'startup-error.log') -Value ("$(Get-Date -Format o) " + $_.Exception.Message)
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message + "`nConsulte data\runtime\startup-error.log.",'Biosaude - Erro ao iniciar') | Out-Null
    exit 1
}
