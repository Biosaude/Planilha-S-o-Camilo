# Executar uma vez, no PowerShell, na pasta do projeto.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$root = (Get-Location).Path
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$launcher = Join-Path $root 'Iniciar-Sao-Camilo.cmd'
Write-Host 'Instalando a ferramenta Biosaude - Hospital Sao Camilo...'
if (-not (Test-Path $python)) {
    & py -3.12 -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 nao encontrado. Instale Python 3.12 e execute novamente.' }
}
& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Falha ao atualizar pip.' }
& $python -m pip install -r (Join-Path $root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Falha no pip check.' }
& $python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Testes falharam. Nao criar atalho.' }
if (-not (Test-Path $launcher)) { throw 'Inicializador ausente.' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'Biosaude - Cotacao Sao Camilo.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Abre o aplicativo local de cotacoes do Hospital Sao Camilo'
$shortcut.Save()
Write-Host ''
Write-Host 'Instalacao concluida. Atalho criado na area de trabalho.'
Write-Host 'Antes de usar, importe as duas bases TUSS privadas conforme docs/WINDOWS11.md.'
