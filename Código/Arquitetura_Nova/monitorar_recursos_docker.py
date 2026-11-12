"""
Coletor Automático de Recursos Computacionais do Docker (24/7)
Arquitetura Nova (ChirpStack + Django + PostgreSQL + Redis + Mosquitto)

Coleta periodicamente via `docker stats --no-stream` o consumo de:
  - CPU (%)
  - Memória RAM (MB e %)
  - Rede (RX / TX em MB)
  - Disco / Block I/O (Leitura / Escrita em MB)
  - Número de Processos/Threads (PIDs)

Salva automaticamente em `monitoramento/recursos_docker.csv`, registrando cada
container individualmente e uma linha consolidada `TOTAL_ARQUITETURA`.
"""
import argparse
import csv
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time

BASE_DIR = Path(__file__).resolve().parent
MONITORAMENTO_DIR = BASE_DIR / "monitoramento"
CSV_PATH = MONITORAMENTO_DIR / "recursos_docker.csv"

PREFIXOS_CONTAINERS = ("smart_campus_",)

UNIDADES_BYTES = {
    "B": 1.0,
    "KB": 1e3,
    "KIB": 1024.0,
    "MB": 1e6,
    "MIB": 1024.0 ** 2,
    "GB": 1e9,
    "GIB": 1024.0 ** 3,
    "TB": 1e12,
    "TIB": 1024.0 ** 4,
}


def converter_para_mb(texto: str) -> float:
    """Converte strings do docker stats (ex: '145.2MiB', '1.2GB', '850kB') para MB."""
    if not texto:
        return 0.0
    m = re.match(r"^\s*([0-9.]+)\s*([a-zA-Z]+)\s*$", texto.strip())
    if not m:
        return 0.0
    valor = float(m.group(1))
    unidade = m.group(2).upper()
    fator = UNIDADES_BYTES.get(unidade, 1.0)
    return (valor * fator) / (1024.0 ** 2)


def formatar_tamanho_auto(valor_mb: float) -> str:
    """Converte automaticamente um valor em MB para KB, MB ou GB."""
    if valor_mb <= 0.0:
        return "0.00 KB"
    if valor_mb < 1.0:
        kb_val = valor_mb * 1024.0
        return f"{kb_val:.2f} KB"
    if valor_mb < 1024.0:
        return f"{valor_mb:.2f} MB"
    gb_val = valor_mb / 1024.0
    return f"{gb_val:.2f} GB"


def formatar_velocidade_auto(valor_mb_s: float) -> str:
    """Converte automaticamente uma taxa em MB/s para B/s, KB/s, MB/s ou GB/s."""
    if valor_mb_s <= 0.0:
        return "0.00 KB/s"
    if valor_mb_s < (1.0 / 1024.0):
        bytes_s = valor_mb_s * (1024.0 ** 2)
        return f"{bytes_s:.0f} B/s"
    if valor_mb_s < 1.0:
        kb_s = valor_mb_s * 1024.0
        return f"{kb_s:.2f} KB/s"
    if valor_mb_s < 1024.0:
        return f"{valor_mb_s:.2f} MB/s"
    gb_s = valor_mb_s / 1024.0
    return f"{gb_s:.2f} GB/s"


# Histórico da coleta anterior para calcular velocidade instantânea de rede (RX/TX por segundo)
_ESTADO_REDE_ANTERIOR: dict[str, tuple[float, float, float]] = {}


def separar_par_io(texto: str) -> tuple[float, float]:
    """Divide '12.4MB / 8.1MB' em (12.4, 8.1) em MB."""
    if not texto or "/" not in texto:
        return 0.0, 0.0
    partes = texto.split("/", 1)
    return converter_para_mb(partes[0]), converter_para_mb(partes[1])


def extrair_float(texto: str) -> float:
    if not texto:
        return 0.0
    limpo = texto.replace("%", "").strip()
    try:
        return float(limpo)
    except ValueError:
        return 0.0


def coletar_amostra(arquitetura: str, usar_agente: str):
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        return []

    agora = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    t_mono = time.monotonic()
    linhas = []

    soma_cpu = 0.0
    soma_mem_mb = 0.0
    mem_limit_ref = 0.0
    soma_net_rx = 0.0
    soma_net_tx = 0.0
    soma_vel_rx_mb_s = 0.0
    soma_vel_tx_mb_s = 0.0
    soma_blk_r = 0.0
    soma_blk_w = 0.0
    soma_pids = 0

    for raw_line in res.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        nome = item.get("Name", "")
        if not nome.startswith(PREFIXOS_CONTAINERS):
            continue

        cpu_pct = extrair_float(item.get("CPUPerc", "0%"))
        mem_usada_mb, mem_limite_mb = separar_par_io(item.get("MemUsage", "0B / 0B"))
        mem_pct = extrair_float(item.get("MemPerc", "0%"))
        net_rx_mb, net_tx_mb = separar_par_io(item.get("NetIO", "0B / 0B"))
        blk_r_mb, blk_w_mb = separar_par_io(item.get("BlockIO", "0B / 0B"))
        pids = int(extrair_float(item.get("PIDs", "0")))

        vel_rx_mb_s = 0.0
        vel_tx_mb_s = 0.0
        if nome in _ESTADO_REDE_ANTERIOR:
            t_ant, rx_ant, tx_ant = _ESTADO_REDE_ANTERIOR[nome]
            dt = max(t_mono - t_ant, 1e-3)
            if net_rx_mb >= rx_ant:
                vel_rx_mb_s = (net_rx_mb - rx_ant) / dt
            if net_tx_mb >= tx_ant:
                vel_tx_mb_s = (net_tx_mb - tx_ant) / dt
        _ESTADO_REDE_ANTERIOR[nome] = (t_mono, net_rx_mb, net_tx_mb)

        soma_cpu += cpu_pct
        soma_mem_mb += mem_usada_mb
        if mem_limite_mb > mem_limit_ref:
            mem_limit_ref = mem_limite_mb
        soma_net_rx += net_rx_mb
        soma_net_tx += net_tx_mb
        soma_vel_rx_mb_s += vel_rx_mb_s
        soma_vel_tx_mb_s += vel_tx_mb_s
        soma_blk_r += blk_r_mb
        soma_blk_w += blk_w_mb
        soma_pids += pids

        linhas.append({
            "timestamp": agora,
            "arquitetura": arquitetura,
            "usar_agente": usar_agente,
            "container": nome,
            "cpu_percent": f"{cpu_pct:.2f}",
            "mem_usage": formatar_tamanho_auto(mem_usada_mb),
            "mem_limit": formatar_tamanho_auto(mem_limite_mb),
            "mem_usage_mb": f"{mem_usada_mb:.2f}",
            "mem_limit_mb": f"{mem_limite_mb:.2f}",
            "mem_percent": f"{mem_pct:.2f}",
            "net_rx": formatar_tamanho_auto(net_rx_mb),
            "net_tx": formatar_tamanho_auto(net_tx_mb),
            "net_rx_speed": formatar_velocidade_auto(vel_rx_mb_s),
            "net_tx_speed": formatar_velocidade_auto(vel_tx_mb_s),
            "net_rx_kbps": f"{vel_rx_mb_s * 1024.0:.2f}",
            "net_tx_kbps": f"{vel_tx_mb_s * 1024.0:.2f}",
            "net_rx_mb": f"{net_rx_mb:.4f}",
            "net_tx_mb": f"{net_tx_mb:.4f}",
            "block_read": formatar_tamanho_auto(blk_r_mb),
            "block_write": formatar_tamanho_auto(blk_w_mb),
            "block_read_mb": f"{blk_r_mb:.4f}",
            "block_write_mb": f"{blk_w_mb:.4f}",
            "pids": pids,
        })

    if linhas:
        mem_pct_total = (soma_mem_mb / mem_limit_ref * 100.0) if mem_limit_ref > 0 else 0.0
        linhas.append({
            "timestamp": agora,
            "arquitetura": arquitetura,
            "usar_agente": usar_agente,
            "container": "TOTAL_ARQUITETURA",
            "cpu_percent": f"{soma_cpu:.2f}",
            "mem_usage": formatar_tamanho_auto(soma_mem_mb),
            "mem_limit": formatar_tamanho_auto(mem_limit_ref),
            "mem_usage_mb": f"{soma_mem_mb:.2f}",
            "mem_limit_mb": f"{mem_limit_ref:.2f}",
            "mem_percent": f"{mem_pct_total:.2f}",
            "net_rx": formatar_tamanho_auto(soma_net_rx),
            "net_tx": formatar_tamanho_auto(soma_net_tx),
            "net_rx_speed": formatar_velocidade_auto(soma_vel_rx_mb_s),
            "net_tx_speed": formatar_velocidade_auto(soma_vel_tx_mb_s),
            "net_rx_kbps": f"{soma_vel_rx_mb_s * 1024.0:.2f}",
            "net_tx_kbps": f"{soma_vel_tx_mb_s * 1024.0:.2f}",
            "net_rx_mb": f"{soma_net_rx:.4f}",
            "net_tx_mb": f"{soma_net_tx:.4f}",
            "block_read": formatar_tamanho_auto(soma_blk_r),
            "block_write": formatar_tamanho_auto(soma_blk_w),
            "block_read_mb": f"{soma_blk_r:.4f}",
            "block_write_mb": f"{soma_blk_w:.4f}",
            "pids": soma_pids,
        })

    return linhas


def main():
    parser = argparse.ArgumentParser(description="Monitor de Recursos Docker - Arquitetura Nova")
    parser.add_argument("--intervalo", type=int, default=15, help="Intervalo em segundos entre coletas (padrão: 15s)")
    parser.add_argument("--usar-agente", type=str, default=os.environ.get("USAR_AGENTE", "1"), help="Flag USAR_AGENTE (1 ou 0)")
    args = parser.parse_args()

    MONITORAMENTO_DIR.mkdir(parents=True, exist_ok=True)
    campos = [
        "timestamp",
        "arquitetura",
        "usar_agente",
        "container",
        "cpu_percent",
        "mem_usage",
        "mem_limit",
        "mem_usage_mb",
        "mem_limit_mb",
        "mem_percent",
        "net_rx",
        "net_tx",
        "net_rx_speed",
        "net_tx_speed",
        "net_rx_kbps",
        "net_tx_kbps",
        "net_rx_mb",
        "net_tx_mb",
        "block_read",
        "block_write",
        "block_read_mb",
        "block_write_mb",
        "pids",
    ]

    print(f">>> [Monitor Docker - Arquitetura_Nova] USAR_AGENTE={args.usar_agente} | Intervalo={args.intervalo}s")
    print(f">>> Salvando continuamente em: {CSV_PATH}")

    while True:
        try:
            amostras = coletar_amostra("Arquitetura_Nova", str(args.usar_agente))
            if amostras:
                escrever_header = not CSV_PATH.exists()
                if not escrever_header:
                    with open(CSV_PATH, mode="r", encoding="utf-8", errors="ignore") as f_in:
                        primeira_linha = f_in.readline().strip()
                    if "net_rx_speed," not in primeira_linha:
                        escrever_header = True
                        with open(CSV_PATH, mode="w", newline="", encoding="utf-8") as f_reset:
                            pass
                with open(CSV_PATH, mode="a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=campos)
                    if escrever_header:
                        writer.writeheader()
                    writer.writerows(amostras)

                resumo = amostras[-1]
                print(
                    f"[{resumo['timestamp'][:19]}] Containers={len(amostras)-1} | "
                    f"CPU={resumo['cpu_percent']}% | "
                    f"RAM={resumo['mem_usage']} ({resumo['mem_percent']}%) | "
                    f"Net RX/TX={resumo['net_rx']} / {resumo['net_tx']} "
                    f"(Vel: {resumo['net_rx_speed']} / {resumo['net_tx_speed']}) | "
                    f"Disco R/W={resumo['block_read']} / {resumo['block_write']}"
                )
            else:
                print(">>> Aguardando containers da Arquitetura Nova iniciarem...")
        except KeyboardInterrupt:
            print("\n>>> Monitoramento encerrado pelo usuário.")
            break
        except Exception as e:
            print(f">>> [Erro no coletor] {e}")

        time.sleep(args.intervalo)


if __name__ == "__main__":
    main()

