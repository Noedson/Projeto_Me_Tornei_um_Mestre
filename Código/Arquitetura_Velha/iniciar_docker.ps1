# Script para subir a Arquitetura Velha (ChirpStack -> Node-RED -> Proxy de Integração -> FIWARE IoT-Agent / Orion -> MongoDB)
# Uso: .\iniciar_docker.ps1 [-d [-t] | -p] [-a | --com-agente | -sa | --sem-agente]
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding           = [System.Text.Encoding]::UTF8
$ErrorActionPreference    = "Stop"
Set-Location $PSScriptRoot

$modo = "desenvolvimento"
$teste = $false
$usarAgente = "0"
foreach ($arg in $args) {
    switch -Regex ($arg) {
        "^(--produ|-p|-produ)"                     { $modo = "producao" }
        "^(--desenvolvimento|-d|-desenv)"          { $modo = "desenvolvimento" }
        "^(--teste|-t|-teste|--test)"              { $teste = $true }
        "^(--sem-agente|-sa|--no-agent)"           { $usarAgente = "0" }
        "^(--com-agente|-a|--agent)"               { $usarAgente = "1" }
    }
}

$iniciarLwn = ($modo -eq "desenvolvimento") -and $teste
$env:APP_TESTE = if ($iniciarLwn) { "1" } else { "0" }
$env:USAR_AGENTE = $usarAgente

Write-Host ">>> [ARQUITETURA VELHA] Fluxo: ChirpStack (8080) -> Node-RED (1880) -> Proxy de Integração (4000) -> FIWARE IoT-Agent (7896) / Orion (1026) -> MongoDB (27017)" -ForegroundColor Magenta
if ($usarAgente -eq "1") {
    Write-Host ">>> Agente Inteligente V4: ATIVADO (USAR_AGENTE=1 -> container velha_agente_ia na porta 5000)" -ForegroundColor Cyan
} else {
    Write-Host ">>> Agente Inteligente V4: DESATIVADO (USAR_AGENTE=0 - Modo Reativo Original calcIQAR) [Para ativar: use -a ou --com-agente]" -ForegroundColor Yellow
}
if ($iniciarLwn) {
    Write-Host ">>> Modo de TESTE (-t) ATIVO: O LWN-Simulator (8002) será iniciado para enviar pacotes LoRaWAN." -ForegroundColor Green
} else {
    Write-Host ">>> LWN-Simulator DESATIVADO (para iniciar com o simulador, execute: .\iniciar_docker.ps1 -d -t)." -ForegroundColor DarkYellow
}

# ==============================================================================
# PASSO 1: Verificar Windows Terminal (com fallback automático para PowerShell)
# ==============================================================================
function Garantir-TerminalAbas {
    $appsPath = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
    if ($env:Path -notlike "*$appsPath*") {
        $env:Path = "$appsPath;$env:Path"
    }
    $wtCmd = Get-Command wt.exe -ErrorAction SilentlyContinue
    if ($wtCmd) { return $wtCmd.Source }
    $wtDireto = Join-Path $appsPath "wt.exe"
    if (Test-Path $wtDireto) { return $wtDireto }
    return $null
}

$caminhoWT = Garantir-TerminalAbas

# ==============================================================================
# PASSO 2: Garantir LF nos scripts .sh e carregar nodered-image.zip se necessário
# ==============================================================================
$shInit = Join-Path $PSScriptRoot "chirpstack-docker\configuration\postgresql\initdb\001-chirpstack_extensions.sh"
if (Test-Path $shInit) {
    $bytes = [System.IO.File]::ReadAllBytes($shInit)
    $textoLF = [System.Text.Encoding]::UTF8.GetString($bytes) -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($shInit, $textoLF, (New-Object System.Text.UTF8Encoding($false)))
}

# Verifica se a imagem nodered/node-red:latest já existe localmente; se não, carrega do nodered-image.zip
$ErrorActionPreference = "Continue"
$noderedImg = docker images -q nodered/node-red:latest 2>$null
$ErrorActionPreference = "Stop"

if (-not $noderedImg) {
    $zipPath = Join-Path $PSScriptRoot "nodered-image.zip"
    $tarPath = Join-Path $PSScriptRoot "nodered-image.tar"
    if (Test-Path $zipPath) {
        Write-Host ">>> Extraindo e carregando a imagem do Node-RED a partir de nodered-image.zip..." -ForegroundColor Cyan
        if (-not (Test-Path $tarPath)) {
            Expand-Archive -Path $zipPath -DestinationPath $PSScriptRoot -Force
        }
        if (Test-Path $tarPath) {
            docker load -i $tarPath
            Remove-Item $tarPath -Force -ErrorAction SilentlyContinue
        }
    }
}

# ==============================================================================
# PASSO 3: Subir todos os containers da Arquitetura Velha
# ==============================================================================
Write-Host "`n>>> [2/3] Construindo e iniciando os containers da Arquitetura Velha..." -ForegroundColor Cyan
$composeProfiles = @()
if ($iniciarLwn) {
    $composeProfiles += "--profile", "teste"
} else {
    $ErrorActionPreference = "Continue"
    docker rm -f velha_lwn_simulator 2>$null | Out-Null
    $ErrorActionPreference = "Stop"
}
if ($usarAgente -eq "1") {
    $composeProfiles += "--profile", "agente"
} else {
    $ErrorActionPreference = "Continue"
    docker rm -f velha_agente_ia 2>$null | Out-Null
    $ErrorActionPreference = "Stop"
}
docker compose @composeProfiles up -d --build

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n>>> [ERRO] O comando 'docker compose' falhou (código $LASTEXITCODE). Verifique se o Docker Desktop está aberto e se a Arquitetura Nova foi parada." -ForegroundColor Red
    exit $LASTEXITCODE
}

# ==============================================================================
# PASSO 4: Abrir terminais de logs
# ==============================================================================
$servicos = @(
    @{ Container = "velha_proxy_integracao";   Titulo = "1. Proxy Integração TS (4000)" },
    @{ Container = "velha_nodered";            Titulo = "2. Node-RED (1880)" },
    @{ Container = "velha_chirpstack";         Titulo = "3. ChirpStack (8080)" },
    @{ Container = "velha_gateway_bridge";     Titulo = "4. Gateway Bridge UDP (1700)" },
    @{ Container = "fiware-iot-agent";         Titulo = "5. FIWARE IoT-Agent UL (4041/7896)" },
    @{ Container = "fiware-orion";             Titulo = "6. FIWARE Orion (1026)" },
    @{ Container = "fiware-cygnus";            Titulo = "7. FIWARE Cygnus (5051/5080)" },
    @{ Container = "db-mongo";                 Titulo = "8. MongoDB (27017)" }
)
if ($usarAgente -eq "1") {
    $servicos += @{ Container = "velha_agente_ia"; Titulo = "9. Agente IA V4 (5000)" }
}
if ($iniciarLwn) {
    $servicos += @{ Container = "velha_lwn_simulator"; Titulo = "10. LWN Simulator (8002)" }
}
$servicos += @{ ComandoHost = "python `"$PSScriptRoot\monitorar_recursos_docker.py`" --usar-agente $usarAgente"; Titulo = "11. Monitor Recursos Docker (CSV)" }

$pidFile = Join-Path $PSScriptRoot ".docker_terminals.pid"
if (Test-Path $pidFile) { Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }

function Abrir-LogsPowerShell {
    Write-Host ">>> Abrindo uma janela de PowerShell para cada container..." -ForegroundColor Yellow
    $pids = @()
    foreach ($s in $servicos) {
        $nome = $s.Container
        $titulo = $s.Titulo
        if ($s.ComandoHost) {
            $logCmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; `$Host.UI.RawUI.WindowTitle = '$titulo'; Write-Host '=== $titulo ===' -ForegroundColor Cyan; $($s.ComandoHost)"
        } else {
            $logCmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; `$Host.UI.RawUI.WindowTitle = '$titulo'; Write-Host '=== LOGS: $titulo ($nome) ===' -ForegroundColor Yellow; docker logs -f $nome"
        }
        $proc = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", $logCmd
        $pids += $proc.Id
    }
    $pids | Set-Content -Path $pidFile
}

Write-Host "`n>>> [3/3] Abrindo terminais de logs..." -ForegroundColor Green

if ($caminhoWT) {
    try {
        Write-Host ">>> Abrindo todos os logs em abas organizadas no Windows Terminal..." -ForegroundColor Cyan
        for ($i = 0; $i -lt $servicos.Count; $i++) {
            $s = $servicos[$i]
            $nome = $s.Container
            $titulo = $s.Titulo
            if ($s.ComandoHost) {
                $logCmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; `$Host.UI.RawUI.WindowTitle = '$titulo'; Write-Host '=== $titulo ===' -ForegroundColor Cyan; `$PID | Out-File -Append -FilePath '$pidFile'; $($s.ComandoHost)"
            } else {
                $logCmd = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; `$Host.UI.RawUI.WindowTitle = '$titulo'; Write-Host '=== LOGS: $titulo ($nome) ===' -ForegroundColor Yellow; `$PID | Out-File -Append -FilePath '$pidFile'; docker logs -f $nome"
            }
            Start-Process $caminhoWT -ArgumentList @("-w", "0", "new-tab", "--title", $titulo, "powershell", "-NoExit", "-Command", $logCmd) -ErrorAction Stop
            if ($i -eq 0) {
                Start-Sleep -Milliseconds 700
            } else {
                Start-Sleep -Milliseconds 250
            }
        }
    } catch {
        Write-Warning "Falha ao abrir o Windows Terminal ($($_.Exception.Message))."
        Write-Host ">>> Alternando automaticamente para janelas padrão do PowerShell..." -ForegroundColor Yellow
        Abrir-LogsPowerShell
    }
} else {
    Abrir-LogsPowerShell
}

Write-Host "`n>>> Pronto! A Arquitetura Velha está rodando e integrada:" -ForegroundColor Green
Write-Host "    - ChirpStack:           http://localhost:8080 (admin / admin)" -ForegroundColor Cyan
Write-Host "    - Node-RED:             http://localhost:1880" -ForegroundColor Cyan
Write-Host "    - Proxy de Integração:  http://localhost:4000/ping" -ForegroundColor Cyan
Write-Host "    - FIWARE Orion:         http://localhost:1026/v2/entities?options=keyValues&type=Sensor (Header: fiware-service: openiot)" -ForegroundColor Cyan
Write-Host "    - FIWARE Monitor:       http://localhost:3000/device/monitor" -ForegroundColor Cyan
if ($iniciarLwn) {
    Write-Host "    - LWN-Simulator:        http://localhost:8002" -ForegroundColor Cyan
}
Write-Host ">>> Para encerrar tudo, execute: .\parar_docker.ps1" -ForegroundColor Yellow

