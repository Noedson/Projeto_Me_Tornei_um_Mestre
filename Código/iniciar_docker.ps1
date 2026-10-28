# Script para subir o Docker Compose e abrir um terminal separado para cada serviço
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ">>> Construindo e iniciando os containers com Docker Compose..." -ForegroundColor Cyan
docker compose up -d --build

$servicos = @(
    @{ Container = "smart_campus_web";                    Titulo = "[SmartCampus] 1. Django + Agente IA (Porta 8000)" },
    @{ Container = "smart_campus_chirpstack";             Titulo = "[SmartCampus] 2. ChirpStack Server (Porta 8080)" },
    @{ Container = "smart_campus_gateway_bridge";         Titulo = "[SmartCampus] 3. Gateway Bridge UDP (Porta 1700)" },
    @{ Container = "smart_campus_mosquitto";              Titulo = "[SmartCampus] 4. MQTT Mosquitto (Porta 1883)" },
    @{ Container = "smart_campus_db";                     Titulo = "[SmartCampus] 5. PostgreSQL (Porta 5432)" },
    @{ Container = "smart_campus_redis";                  Titulo = "[SmartCampus] 6. Redis (Porta 6379)" },
    @{ Container = "smart_campus_chirpstack_rest_api";    Titulo = "[SmartCampus] 7. ChirpStack REST API (Porta 8090)" }
)

$pids = @()
Write-Host ">>> Abrindo um terminal para cada container..." -ForegroundColor Green
foreach ($s in $servicos) {
    $nome = $s.Container
    $titulo = $s.Titulo
    $proc = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$titulo'; Write-Host '=== LOGS: $titulo ($nome) ===' -ForegroundColor Yellow; docker logs -f $nome"
    $pids += $proc.Id
}

$pids | Set-Content -Path (Join-Path $PSScriptRoot ".docker_terminals.pid")
Write-Host ">>> Pronto! Todos os terminais foram abertos. Para encerrar tudo, rode .\parar_docker.ps1" -ForegroundColor Green
