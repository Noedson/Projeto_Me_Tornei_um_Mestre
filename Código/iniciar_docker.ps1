# Script para subir o Docker Compose e abrir as logs em abas no Windows Terminal
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# ==============================================================================
# PASSO 1: Detectar / Instalar Terminal capaz de abrir abas (Windows Terminal)
# Deve ser feito ANTES da instalação dos pacotes Python no Docker Build
# ==============================================================================
function Garantir-TerminalAbas {
    Write-Host ">>> [1/3] Verificando terminal com suporte a abas..." -ForegroundColor Cyan

    # Atualiza PATH atual para garantir que caminhos do WindowsApps sejam reconhecidos
    $appsPath = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
    if ($env:Path -notlike "*$appsPath*") {
        $env:Path = "$appsPath;$env:Path"
    }

    # 1. Verifica se 'wt.exe' já está disponível
    $wtCmd = Get-Command wt.exe -ErrorAction SilentlyContinue
    if ($wtCmd) {
        Write-Host ">>> Windows Terminal detectado: $($wtCmd.Source)" -ForegroundColor Green
        return $wtCmd.Source
    }

    # 2. Verifica se o executável existe no diretório padrão do WindowsApps
    $wtDireto = Join-Path $appsPath "wt.exe"
    if (Test-Path $wtDireto) {
        Write-Host ">>> Windows Terminal detectado em: $wtDireto" -ForegroundColor Green
        return $wtDireto
    }

    # 3. Caso não tenha, tenta instalar via winget
    Write-Host ">>> Terminal com suporte a abas não encontrado no sistema." -ForegroundColor Yellow
    Write-Host ">>> Iniciando verificação de instalação do Windows Terminal..." -ForegroundColor Cyan

    $wingetCmd = Get-Command winget.exe -ErrorAction SilentlyContinue
    $wingetPath = if ($wingetCmd) { $wingetCmd.Source } else { Join-Path $appsPath "winget.exe" }

    if (-not (Test-Path $wingetPath)) {
        Write-Warning "winget não foi encontrado no sistema para automação. Continuando com janelas normais do PowerShell."
        return $null
    }

    Write-Host ">>> Instalando Windows Terminal (Microsoft.WindowsTerminal)..." -ForegroundColor Cyan
    
    # Tenta instalação para o usuário atual
    $instArgs = "install --id Microsoft.WindowsTerminal -e --accept-source-agreements --accept-package-agreements"
    $proc = Start-Process -FilePath $wingetPath -ArgumentList $instArgs -Wait -PassThru -NoNewWindow

    # Se a instalação falhar ou exigir permissão de administrador
    if ($proc.ExitCode -ne 0) {
        Write-Host ">>> A instalação requer permissão administrativa. Solicitando autorização (UAC)..." -ForegroundColor Yellow
        try {
            Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -Command `"Start-Process '$wingetPath' -ArgumentList '$instArgs' -Verb RunAs -Wait`"" -Verb RunAs -Wait
        } catch {
            Write-Warning "Não foi possível obter permissão de administrador."
        }
    }

    # Revalida se o wt.exe ficou disponível após a instalação
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User") + ";$appsPath"
    $wtCmd = Get-Command wt.exe -ErrorAction SilentlyContinue
    if ($wtCmd) {
        Write-Host ">>> Windows Terminal instalado com sucesso e pronto para uso!" -ForegroundColor Green
        return $wtCmd.Source
    } elseif (Test-Path $wtDireto) {
        Write-Host ">>> Windows Terminal instalado com sucesso em: $wtDireto" -ForegroundColor Green
        return $wtDireto
    } else {
        Write-Warning "A instalação do Windows Terminal não pôde ser concluída. O script usará janelas separadas do PowerShell como alternativa."
        return $null
    }
}

$caminhoWT = Garantir-TerminalAbas

# ==============================================================================
# PASSO 2: Construir e iniciar os containers (instalação de pacotes Python, etc.)
# ==============================================================================
Write-Host "`n>>> [2/3] Construindo e iniciando os containers com Docker Compose..." -ForegroundColor Cyan
Write-Host "    (Isso pode levar alguns minutos caso precise instalar os pacotes Python no Docker)" -ForegroundColor Gray
docker compose up -d --build

# ==============================================================================
# PASSO 3: Abrir logs dos serviços em abas no Windows Terminal (ou janelas normais)
# ==============================================================================
$servicos = @(
    @{ Container = "smart_campus_web";                    Titulo = "1. Django + Agente IA (8000)" },
    @{ Container = "smart_campus_chirpstack";             Titulo = "2. ChirpStack (8080)" },
    @{ Container = "smart_campus_gateway_bridge";         Titulo = "3. Gateway Bridge UDP (1700)" },
    @{ Container = "smart_campus_mosquitto";              Titulo = "4. Mosquitto MQTT (1883)" },
    @{ Container = "smart_campus_db";                     Titulo = "5. PostgreSQL (5432)" },
    @{ Container = "smart_campus_redis";                  Titulo = "6. Redis (6379)" },
    @{ Container = "smart_campus_chirpstack_rest_api";    Titulo = "7. REST API (8090)" }
)

$pidFile = Join-Path $PSScriptRoot ".docker_terminals.pid"
if (Test-Path $pidFile) { Remove-Item $pidFile -Force -ErrorAction SilentlyContinue }

Write-Host "`n>>> [3/3] Abrindo terminais de logs..." -ForegroundColor Green

if ($caminhoWT) {
    Write-Host ">>> Abrindo todos os logs em abas organizadas no Windows Terminal..." -ForegroundColor Cyan
    for ($i = 0; $i -lt $servicos.Count; $i++) {
        $s = $servicos[$i]
        $nome = $s.Container
        $titulo = $s.Titulo
        
        $logCmd = "`$Host.UI.RawUI.WindowTitle = '$titulo'; Write-Host '=== LOGS: $titulo ($nome) ===' -ForegroundColor Yellow; `$PID | Out-File -Append -FilePath '$pidFile'; docker logs -f $nome"
        
        # O parâmetro -w 0 anexa novas abas na mesma janela (Janela 0)
        Start-Process $caminhoWT -ArgumentList @("-w", "0", "new-tab", "--title", $titulo, "powershell", "-NoExit", "-Command", $logCmd)
        
        # Pausa para o Windows Terminal inicializar a janela na primeira aba
        if ($i -eq 0) {
            Start-Sleep -Milliseconds 700
        } else {
            Start-Sleep -Milliseconds 250
        }
    }
} else {
    Write-Host ">>> Abrindo uma janela de PowerShell para cada container..." -ForegroundColor Yellow
    $pids = @()
    foreach ($s in $servicos) {
        $nome = $s.Container
        $titulo = $s.Titulo
        $logCmd = "`$Host.UI.RawUI.WindowTitle = '$titulo'; Write-Host '=== LOGS: $titulo ($nome) ===' -ForegroundColor Yellow; docker logs -f $nome"
        $proc = Start-Process powershell -PassThru -ArgumentList "-NoExit", "-Command", $logCmd
        $pids += $proc.Id
    }
    $pids | Set-Content -Path $pidFile
}

Write-Host "`n>>> Pronto! Todos os serviços estão rodando e os logs foram abertos." -ForegroundColor Green
Write-Host ">>> Para encerrar os containers e fechar os terminais, execute: .\parar_docker.ps1" -ForegroundColor Cyan

