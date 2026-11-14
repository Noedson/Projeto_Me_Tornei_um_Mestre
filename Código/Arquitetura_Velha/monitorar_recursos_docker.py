"""
Coletor Automático de Recursos Computacionais do Docker (24/7)
Arquitetura Velha (ChirpStack + Node-RED + Proxy TS + FIWARE IoT-Agent/Orion/Cygnus + MongoDB + Agente IA Opcional)

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
MONITORAMENTO_DIR = BASE_DIR / "monitoramento"
CSV_PATH = MONITORAMENTO_DIR / "recursos_docker.csv"
DB_PATH = MONITORAMENTO_DIR / "metricas_experimento.db"
ESTADO_AGENTE_PATH = MONITORAMENTO_DIR / "estado_agente.json"
CSV_LEITURAS_PATH = MONITORAMENTO_DIR / "metricas_processamento_leituras.csv"


def ler_estado(padrao: str = "0") -> str:
    if ESTADO_AGENTE_PATH.exists():
        try:
            dados = json.loads(ESTADO_AGENTE_PATH.read_text(encoding="utf-8"))
            return "1" if str(dados.get("usar_agente", padrao)) in ("1", "true", "True") else "0"
        except Exception:
            pass
    return str(padrao)


def salvar_estado_agente(usar_agente: str):
    MONITORAMENTO_DIR.mkdir(parents=True, exist_ok=True)
    valor = 1 if str(usar_agente) in ("1", "true", "True") else 0
    ESTADO_AGENTE_PATH.write_text(json.dumps({"usar_agente": valor}), encoding="utf-8")


DB_LOCK = threading.Lock()


def inicializar_sqlite():
    MONITORAMENTO_DIR.mkdir(parents=True, exist_ok=True)
    with DB_LOCK:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS recursos_docker(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                arquitetura TEXT,
                usar_agente INTEGER,
                container TEXT,
                cpu_percent REAL,
                mem_usage_mb REAL,
                mem_limit_mb REAL,
                net_rx_kbps REAL,
                net_tx_kbps REAL,
                block_read_mb REAL,
                block_write_mb REAL,
                pids INTEGER
            )
        """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS leituras_processamento(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_recebimento TEXT,
                timestamp_sensor TEXT,
                arquitetura TEXT,
                usar_agente INTEGER,
                dev_eui TEXT,
                co_atual REAL,
                iqar_reativo_presente TEXT,
                alerta_reativo_presente INTEGER,
                iqar_previsto_15m TEXT,
                co_previsto_15m REAL,
                anomalia_detectada INTEGER,
                erro_reconstrucao REAL,
                tipo_alerta_agente TEXT,
                latencia_total_ms REAL,
                latencia_agente_ms REAL
            )
        """)


def salvar_leitura_sqlite(d: dict):
    with DB_LOCK:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            conn.execute("""
                INSERT INTO leituras_processamento(
                    timestamp_recebimento, timestamp_sensor, arquitetura, usar_agente,
                    dev_eui, co_atual, iqar_reativo_presente, alerta_reativo_presente,
                    iqar_previsto_15m, co_previsto_15m, anomalia_detectada,
                    erro_reconstrucao, tipo_alerta_agente, latencia_total_ms, latencia_agente_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d.get("timestamp_recebimento"),
                d.get("timestamp_sensor"),
                d.get("arquitetura", "Arquitetura_Velha"),
                int(d.get("usar_agente", 0)),
                d.get("dev_eui"),
                float(d["co_atual"]) if d.get("co_atual") not in (None, "") else None,
                d.get("iqar_reativo_presente"),
                int(d.get("alerta_reativo_presente", 0)),
                d.get("iqar_previsto_15m") or None,
                float(d["co_previsto_15m"]) if d.get("co_previsto_15m") not in (None, "") else None,
                int(d["anomalia_detectada"]) if d.get("anomalia_detectada") not in (None, "") else None,
                float(d["erro_reconstrucao"]) if d.get("erro_reconstrucao") not in (None, "") else None,
                d.get("tipo_alerta_agente") or None,
                float(d["latencia_total_ms"]) if d.get("latencia_total_ms") not in (None, "") else None,
                float(d["latencia_agente_ms"]) if d.get("latencia_agente_ms") not in (None, "") else None,
            ))


def salvar_amostras_sqlite(amostras: list[dict]):
    with DB_LOCK:
        with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
            conn.executemany("""
            INSERT INTO recursos_docker(
                timestamp, arquitetura, usar_agente, container,
                cpu_percent, mem_usage_mb, mem_limit_mb,
                net_rx_kbps, net_tx_kbps, block_read_mb, block_write_mb, pids
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                a["timestamp"],
                a["arquitetura"],
                int(a["usar_agente"]),
                a["container"],
                float(a["cpu_percent"]),
                float(a["mem_usage_mb"]),
                float(a["mem_limit_mb"]),
                float(a["net_rx_kbps"]),
                float(a["net_tx_kbps"]),
                float(a["block_read_mb"]),
                float(a["block_write_mb"]),
                int(a["pids"]),
            ) for a in amostras
        ])


class SyncAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _enviar_json(self, status: int, payload: dict):
        corpo = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(corpo)

    def do_OPTIONS(self):
        self._enviar_json(200, {"ok": True})

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/sync":
            return self._enviar_json(404, {"erro": "Rota nao encontrada"})
        qs = parse_qs(parsed.query)
        after_id = int(qs.get("after_id", ["0"])[0])
        limite = int(qs.get("limit", ["500"])[0])
        with DB_LOCK:
            with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
                conn.row_factory = sqlite3.Row
                linhas = conn.execute(
                    "SELECT * FROM recursos_docker WHERE id > ? ORDER BY id ASC LIMIT ?",
                    (after_id, limite),
                ).fetchall()
                leituras_rows = conn.execute(
                    "SELECT * FROM leituras_processamento ORDER BY id DESC LIMIT 100"
                ).fetchall()
        leituras = [dict(r) for r in reversed(leituras_rows)]
        self._enviar_json(200, {
            "arquitetura": "Arquitetura_Velha",
            "usar_agente": int(ler_estado("0")),
            "recursos": [dict(r) for r in linhas],
            "leituras": leituras,
        })

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(tamanho).decode("utf-8") or "{}")
        if self.path == "/api/leitura":
            salvar_leitura_sqlite(body)
            return self._enviar_json(200, {"ok": True})
        if self.path != "/api/agente":
            return self._enviar_json(404, {"erro": "Rota nao encontrada"})
        novo_estado = "1" if str(body.get("usar_agente", "0")) in ("1", "true", "True") else "0"
        salvar_estado_agente(novo_estado)
        # Inicia ou para o container velha_agente_ia se existir no Docker
        acao = "start" if novo_estado == "1" else "stop"
        subprocess.run(["docker", acao, "velha_agente_ia"], capture_output=True)
        print(f">>> [API Controle - Arq. Velha] Estado USAR_AGENTE alterado para: {novo_estado}")
        self._enviar_json(200, {"ok": True, "usar_agente": int(novo_estado)})

PREFIXOS_CONTAINERS = ("velha_", "fiware-", "db-mongo", "grafana")

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
    parser = argparse.ArgumentParser(description="Monitor de Recursos Docker - Arquitetura Velha")
    parser.add_argument("--intervalo", type=int, default=5, help="Intervalo em segundos entre coletas (padrão: 5s)")
    parser.add_argument("--usar-agente", type=str, default=os.environ.get("USAR_AGENTE", "0"), help="Flag USAR_AGENTE (1 ou 0)")
    args = parser.parse_args()

    MONITORAMENTO_DIR.mkdir(parents=True, exist_ok=True)
    inicializar_sqlite()
    if not ESTADO_AGENTE_PATH.exists():
        salvar_estado_agente(args.usar_agente)

    porta_api = int(os.environ.get("MONITOR_PORT", "9096"))
    servidor_http = ThreadingHTTPServer(("0.0.0.0", porta_api), SyncAPIHandler)
    threading.Thread(target=servidor_http.serve_forever, daemon=True).start()
    print(f">>> [API Sync] Escutando na porta {porta_api} (/api/sync e /api/agente)")

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

    print(f">>> [Monitor Docker - Arquitetura_Velha] USAR_AGENTE={ler_estado(args.usar_agente)} | Intervalo={args.intervalo}s")
    print(f">>> Salvando continuamente no SQLite: {DB_PATH}")

    while True:
        try:
            estado_atual = ler_estado(str(args.usar_agente))
            amostras = coletar_amostra("Arquitetura_Velha", estado_atual)
            if amostras:
                salvar_amostras_sqlite(amostras)

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
                print(">>> Aguardando containers da Arquitetura Velha iniciarem...")
        except KeyboardInterrupt:
            print("\n>>> Monitoramento encerrado pelo usuário.")
            break
        except Exception as e:
            print(f">>> [Erro no coletor] {e}")

        time.sleep(args.intervalo)


if __name__ == "__main__":
    main()

