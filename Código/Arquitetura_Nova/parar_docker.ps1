# Script para parar os containers do Docker Compose e fechar todos os terminais de logs abertos
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot

Write-Host ">>> Parando os containers do Docker Compose..." -ForegroundColor Cyan
docker compose --profile teste down

Write-Host ">>> Fechando as janelas de terminais dos serviços..." -ForegroundColor Yellow

# 1. Fecha pelos PIDs salvos pelo iniciar_docker.ps1 (fecha as abas do Windows Terminal ou janelas)
$pidFile = Join-Path $PSScriptRoot ".docker_terminals.pid"
if (Test-Path $pidFile) {
    $pids = Get-Content $pidFile
    foreach ($id in $pids) {
        if ($id -match '^\d+$') {
            # Encerra processos filhos (como docker.exe logs) se ainda estiverem ativos
            Get-CimInstance Win32_Process -Filter "ParentProcessId = $id" -ErrorAction SilentlyContinue | ForEach-Object {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 2. Fecha também qualquer janela do PowerShell com título dos containers (caso abertas fora do Windows Terminal)
$nomes = @(
    "smart_campus_",
    "[SmartCampus]",
    "1. Django + Agente IA",
    "2. ChirpStack",
    "3. Gateway Bridge UDP",
    "4. Mosquitto",
    "5. PostgreSQL",
    "6. Redis",
    "7. REST API",
    "8. LWN Simulator"
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

Write-Host ">>> Pronto! Todos os containers foram parados e os terminais fechados." -ForegroundColor Green
