# Script para parar os containers da Arquitetura Velha e fechar os terminais de logs
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

Write-Host ">>> Parando os containers da Arquitetura Velha..." -ForegroundColor Cyan
docker compose --profile teste down

Write-Host ">>> Fechando as janelas de terminais dos serviços..." -ForegroundColor Yellow

$pidFile = Join-Path $PSScriptRoot ".docker_terminals.pid"
if (Test-Path $pidFile) {
    $pids = Get-Content $pidFile
    foreach ($id in $pids) {
        if ($id -match '^\d+$') {
            Get-CimInstance Win32_Process -Filter "ParentProcessId = $id" -ErrorAction SilentlyContinue | ForEach-Object {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$nomes = @(
    "velha_",
    "1. Proxy Integração",
    "2. Node-RED",
    "3. ChirpStack",
    "4. Gateway Bridge UDP",
    "5. FIWARE IoT-Agent",
    "6. FIWARE Orion",
    "7. FIWARE Cygnus",
    "8. MongoDB",
    "9. LWN Simulator"
)

foreach ($proc in (Get-Process powershell -ErrorAction SilentlyContinue)) {
    if ($proc.Id -eq $PID -or [string]::IsNullOrEmpty($proc.MainWindowTitle)) { continue }
    foreach ($padrao in $nomes) {
        if ($proc.MainWindowTitle.Contains($padrao)) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            break
        }
    }
}

Write-Host ">>> Pronto! Todos os containers da Arquitetura Velha foram parados e os terminais fechados." -ForegroundColor Green

