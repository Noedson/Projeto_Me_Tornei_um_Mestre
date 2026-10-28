# Script para parar os containers do Docker Compose e fechar todos os terminais de logs abertos
Set-Location $PSScriptRoot

Write-Host ">>> Parando os containers do Docker Compose..." -ForegroundColor Cyan
docker compose down

Write-Host ">>> Fechando as janelas de terminais dos serviços..." -ForegroundColor Yellow

# 1. Fecha pelos PIDs salvos pelo iniciar_docker.ps1
$pidFile = Join-Path $PSScriptRoot ".docker_terminals.pid"
if (Test-Path $pidFile) {
    $pids = Get-Content $pidFile
    foreach ($id in $pids) {
        if ($id -match '^\d+$') {
            Stop-Process -Id ([int]$id) -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 2. Fecha também qualquer janela do PowerShell com título dos containers (mesmo que tenha sido aberta antes)
$nomes = @(
    "smart_campus_",
    "[SmartCampus]",
    "1. Django + Agente IA",
    "2. ChirpStack Server",
    "3. Gateway Bridge UDP",
    "4. MQTT Mosquitto",
    "5. PostgreSQL",
    "6. Redis",
    "7. ChirpStack REST API"
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
