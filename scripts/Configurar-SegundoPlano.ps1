$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$start = Join-Path $root 'Iniciar-Sao-Camilo-SegundoPlano.vbs'
$stop = Join-Path $root 'Encerrar-Sao-Camilo.vbs'
if (-not (Test-Path $start) -or -not (Test-Path $stop)) { throw 'Arquivos de segundo plano ausentes. Baixe a versao atualizada do repositorio.' }
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
foreach ($item in @(
    @{Name='Biosaude - Cotacao Sao Camilo.lnk';Target=$start;Description='Abre a cotacao em segundo plano'},
    @{Name='Biosaude - Encerrar Sao Camilo.lnk';Target=$stop;Description='Encerra o servidor local de cotacoes'}
)) {
    $shortcut = $shell.CreateShortcut((Join-Path $desktop $item.Name))
    $shortcut.TargetPath = 'C:\Windows\System32\wscript.exe'
    $shortcut.Arguments = '"' + $item.Target + '"'
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = $item.Description
    $shortcut.Save()
}
Write-Host 'Atalhos de segundo plano configurados na area de trabalho.'
Write-Host 'Use Biosaude - Cotacao Sao Camilo para abrir e Biosaude - Encerrar Sao Camilo para parar.'
