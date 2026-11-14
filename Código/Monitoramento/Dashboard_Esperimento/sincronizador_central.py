"""
Sincronizador Central ("Repique") + API para o Dashboard React (3ª Máquina)

1. Conecta ao PostgreSQL Central (db-central) da 3ª Máquina.
2. A cada 5 segundos, puxa incrementalmente (WHERE id > ultimo_id) os dados
   dos SQLites locais da Máquina 1 (Arquitetura Velha - porta 9096) e da
   Máquina 2 (Arquitetura Nova - porta 9095) e grava no PostgreSQL Central.
3. Expõe na porta 9090:
   - GET  /api/dashboard       -> Histórico, médias comparativas e status atual
   - POST /api/controle-agente -> Liga/Desliga o Agente nas 2 arquiteturas
   - POST /api/config-urls     -> Atualiza os IPs das 2 máquinas em tempo real
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2.extras import RealDictCursor

PG_CONFIG = {
    "host": os.environ.get("POSTGRES_HOST", "db-central"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "dbname": os.environ.get("POSTGRES_DB", "experimento_mestrado"),
    "user": os.environ.get("POSTGRES_USER", "postgres"),
    "password": os.environ.get("POSTGRES_PASSWORD", "postgres_password"),
}

ESTADO_CONEXAO = {
    "Arquitetura_Nova": {
        "url": os.environ.get("URL_ARQ_NOVA", "http://host.docker.internal:9095").rstrip("/"),
        "online": False,
        "usar_agente": 1,
        "ultimo_sync": None,
    },
    "Arquitetura_Velha": {
        "url": os.environ.get("URL_ARQ_VELHA", "http://host.docker.internal:9096").rstrip("/"),
        "online": False,
        "usar_agente": 0,
        "ultimo_sync": None,
    },
}


def get_conn():
    return psycopg2.connect(**PG_CONFIG)


def inicializar_postgres():
    for tentativa in range(15):
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS recursos_central (
                            id SERIAL PRIMARY KEY,
                            origem_id INTEGER NOT NULL,
                            arquitetura TEXT NOT NULL,
                            timestamp TEXT NOT NULL,
                            usar_agente INTEGER NOT NULL,
                            container TEXT NOT NULL,
                            cpu_percent DOUBLE PRECISION,
                            mem_usage_mb DOUBLE PRECISION,
                            mem_limit_mb DOUBLE PRECISION,
                            net_rx_kbps DOUBLE PRECISION,
                            net_tx_kbps DOUBLE PRECISION,
                            block_read_mb DOUBLE PRECISION,
                            block_write_mb DOUBLE PRECISION,
                            pids INTEGER,
                            UNIQUE(arquitetura, origem_id)
                        );
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_recursos_arq_cont_id
                        ON recursos_central (arquitetura, container, origem_id DESC);
                    """)
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS leituras_central (
                            id SERIAL PRIMARY KEY,
                            arquitetura TEXT NOT NULL,
                            timestamp_recebimento TEXT NOT NULL,
                            timestamp_sensor TEXT,
                            usar_agente INTEGER,
                            dev_eui TEXT,
                            co_atual DOUBLE PRECISION,
                            iqar_reativo_presente TEXT,
                            alerta_reativo_presente INTEGER,
                            iqar_previsto_15m TEXT,
                            co_previsto_15m DOUBLE PRECISION,
                            anomalia_detectada INTEGER,
                            erro_reconstrucao DOUBLE PRECISION,
                            tipo_alerta_agente TEXT,
                            latencia_total_ms DOUBLE PRECISION,
                            latencia_agente_ms DOUBLE PRECISION,
                            UNIQUE(arquitetura, timestamp_recebimento)
                        );
                    """)
            print(">>> [PostgreSQL Central] Tabelas 'recursos_central' e 'leituras_central' prontas!")
            return
        except Exception as e:
            print(f">>> Aguardando PostgreSQL Central ({tentativa+1}/15): {e}")
            time.sleep(2)


def _float_or_none(v):
    if v in (None, ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _int_or_none(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def sincronizar_arquitetura(nome_arq: str):
    info = ESTADO_CONEXAO[nome_arq]
    base_url = info["url"]

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(MAX(origem_id), 0) FROM recursos_central WHERE arquitetura = %s;",
                    (nome_arq,),
                )
                ultimo_id = cur.fetchone()[0]

        req_url = f"{base_url}/api/sync?after_id={ultimo_id}&limit=500"
        req = urllib.request.Request(req_url, method="GET")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            dados = json.loads(resp.read().decode("utf-8"))

        info["online"] = True
        info["usar_agente"] = int(dados.get("usar_agente", info["usar_agente"]))
        info["ultimo_sync"] = time.strftime("%H:%M:%S")

        recursos = dados.get("recursos", [])
        leituras = dados.get("leituras", [])

        if recursos or leituras:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    for r in recursos:
                        cur.execute("""
                            INSERT INTO recursos_central (
                                origem_id, arquitetura, timestamp, usar_agente, container,
                                cpu_percent, mem_usage_mb, mem_limit_mb,
                                net_rx_kbps, net_tx_kbps, block_read_mb, block_write_mb, pids
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (arquitetura, origem_id) DO NOTHING;
                        """, (
                            int(r["id"]), nome_arq, r["timestamp"], int(r["usar_agente"]), r["container"],
                            _float_or_none(r.get("cpu_percent")),
                            _float_or_none(r.get("mem_usage_mb")),
                            _float_or_none(r.get("mem_limit_mb")),
                            _float_or_none(r.get("net_rx_kbps")),
                            _float_or_none(r.get("net_tx_kbps")),
                            _float_or_none(r.get("block_read_mb")),
                            _float_or_none(r.get("block_write_mb")),
                            _int_or_none(r.get("pids")),
                        ))

                    for l in leituras:
                        ts_rec = l.get("timestamp_recebimento")
                        if not ts_rec:
                            continue
                        cur.execute("""
                            INSERT INTO leituras_central (
                                arquitetura, timestamp_recebimento, timestamp_sensor, usar_agente,
                                dev_eui, co_atual, iqar_reativo_presente, alerta_reativo_presente,
                                iqar_previsto_15m, co_previsto_15m, anomalia_detectada,
                                erro_reconstrucao, tipo_alerta_agente, latencia_total_ms, latencia_agente_ms
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (arquitetura, timestamp_recebimento) DO NOTHING;
                        """, (
                            nome_arq,
                            ts_rec,
                            l.get("timestamp_sensor"),
                            _int_or_none(l.get("usar_agente")),
                            l.get("dev_eui"),
                            _float_or_none(l.get("co_atual")),
                            l.get("iqar_reativo_presente"),
                            _int_or_none(l.get("alerta_reativo_presente")),
                            l.get("iqar_previsto_15m") or None,
                            _float_or_none(l.get("co_previsto_15m")),
                            _int_or_none(l.get("anomalia_detectada")),
                            _float_or_none(l.get("erro_reconstrucao")),
                            l.get("tipo_alerta_agente") or None,
                            _float_or_none(l.get("latencia_total_ms")),
                            _float_or_none(l.get("latencia_agente_ms")),
                        ))
    except Exception:
        info["online"] = False


def loop_sincronizacao():
    while True:
        sincronizar_arquitetura("Arquitetura_Nova")
        sincronizar_arquitetura("Arquitetura_Velha")
        time.sleep(1)


JANELAS_CONFIG = {
    "1h": ("1 hour", "1 minute"),
    "24h": ("24 hours", "15 minutes"),
    "7d": ("7 days", "2 hours"),
    "15d": ("15 days", "4 hours"),
}


def obter_dados_dashboard(janela: str = "5m"):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Última amostra instantânea + Histórico TOTAL_ARQUITETURA conforme janela
            historico = {}
            atual = {}
            for arq in ("Arquitetura_Nova", "Arquitetura_Velha"):
                cur.execute("""
                    SELECT origem_id, timestamp, usar_agente, cpu_percent, mem_usage_mb,
                           net_rx_kbps, net_tx_kbps
                    FROM recursos_central
                    WHERE arquitetura = %s AND container = 'TOTAL_ARQUITETURA'
                    ORDER BY origem_id DESC
                    LIMIT 1;
                """, (arq,))
                atual[arq] = cur.fetchone()

                if janela in JANELAS_CONFIG:
                    intervalo_total, bucket_step = JANELAS_CONFIG[janela]
                    cur.execute(f"""
                        SELECT
                            MAX(origem_id) AS origem_id,
                            MAX(timestamp) AS timestamp,
                            ROUND(AVG(usar_agente))::int AS usar_agente,
                            ROUND(AVG(cpu_percent)::numeric, 2) AS cpu_percent,
                            ROUND(AVG(mem_usage_mb)::numeric, 2) AS mem_usage_mb,
                            ROUND(AVG(net_rx_kbps)::numeric, 2) AS net_rx_kbps,
                            ROUND(AVG(net_tx_kbps)::numeric, 2) AS net_tx_kbps
                        FROM recursos_central
                        WHERE arquitetura = %s
                          AND container = 'TOTAL_ARQUITETURA'
                          AND timestamp::timestamptz >= NOW() - INTERVAL '{intervalo_total}'
                        GROUP BY date_bin(INTERVAL '{bucket_step}', timestamp::timestamptz, TIMESTAMPTZ '2000-01-01 00:00:00+00')
                        ORDER BY MIN(timestamp::timestamptz) ASC;
                    """, (arq,))
                    historico[arq] = [dict(r) for r in cur.fetchall()]
                else:
                    cur.execute("""
                        SELECT origem_id, timestamp, usar_agente, cpu_percent, mem_usage_mb,
                               net_rx_kbps, net_tx_kbps, block_read_mb, block_write_mb, pids
                        FROM recursos_central
                        WHERE arquitetura = %s AND container = 'TOTAL_ARQUITETURA'
                        ORDER BY origem_id DESC
                        LIMIT 60;
                    """, (arq,))
                    rows = list(cur.fetchall())
                    rows.reverse()
                    historico[arq] = rows

            # 2. Médias consolidadas por (arquitetura, usar_agente) — Os 4 Cenários!
            cur.execute("""
                SELECT
                    arquitetura,
                    usar_agente,
                    COUNT(*) AS amostras,
                    ROUND(AVG(cpu_percent)::numeric, 2) AS cpu_media,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cpu_percent)::numeric, 2) AS cpu_mediana,
                    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY cpu_percent)::numeric, 2) AS cpu_p95,
                    ROUND(COALESCE(STDDEV_SAMP(cpu_percent), 0)::numeric, 2) AS cpu_desvio,
                    ROUND(MAX(cpu_percent)::numeric, 2) AS cpu_pico,
                    ROUND(AVG(mem_usage_mb)::numeric, 2) AS ram_media_mb,
                    ROUND(AVG(net_rx_kbps + net_tx_kbps)::numeric, 2) AS rede_media_kbps
                FROM recursos_central
                WHERE container = 'TOTAL_ARQUITETURA'
                GROUP BY arquitetura, usar_agente
                ORDER BY arquitetura, usar_agente;
            """)
            resumo_recursos = [dict(r) for r in cur.fetchall()]

            # 3. Médias de latência e alertas por (arquitetura, usar_agente)
            cur.execute("""
                SELECT
                    arquitetura,
                    usar_agente,
                    COUNT(*) AS total_leituras,
                    ROUND(AVG(latencia_total_ms)::numeric, 2) AS latencia_total_media_ms,
                    ROUND(AVG(latencia_agente_ms)::numeric, 2) AS latencia_agente_media_ms,
                    SUM(CASE WHEN alerta_reativo_presente = 1 THEN 1 ELSE 0 END) AS alertas_reativos,
                    SUM(CASE WHEN tipo_alerta_agente IS NOT NULL AND tipo_alerta_agente != '' THEN 1 ELSE 0 END) AS alertas_preditivos
                FROM leituras_central
                GROUP BY arquitetura, usar_agente
                ORDER BY arquitetura, usar_agente;
            """)
            resumo_leituras = [dict(r) for r in cur.fetchall()]

            # 4. Últimas 30 leituras processadas
            cur.execute("""
                SELECT *
                FROM leituras_central
                ORDER BY id DESC
                LIMIT 30;
            """)
            ultimas_leituras = [dict(r) for r in cur.fetchall()]

    return {
        "conexoes": ESTADO_CONEXAO,
        "atual": atual,
        "janela": janela,
        "historico": historico,
        "resumo_recursos": resumo_recursos,
        "resumo_leituras": resumo_leituras,
        "ultimas_leituras": ultimas_leituras,
    }


def _normalizar_url(url: str) -> str:
    u = str(url).strip().rstrip("/")
    if not u:
        return u
    if not u.startswith(("http://", "https://")):
        u = f"http://{u}"
    return u.replace("://localhost", "://host.docker.internal").replace("://127.0.0.1", "://host.docker.internal")


class CentralAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _enviar_json(self, status: int, payload: dict):
        corpo = json.dumps(payload, default=float).encode("utf-8")
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
        if parsed.path == "/api/dashboard":
            try:
                qs = parse_qs(parsed.query)
                janela = qs.get("janela", ["5m"])[0]
                dados = obter_dados_dashboard(janela)
                return self._enviar_json(200, dados)
            except Exception as e:
                return self._enviar_json(500, {"erro": str(e)})
        return self._enviar_json(404, {"erro": "Rota nao encontrada"})

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(tamanho).decode("utf-8") or "{}")

        if self.path == "/api/controle-agente":
            alvo = body.get("alvo", "ambas")
            usar_agente = 1 if str(body.get("usar_agente", 1)) in ("1", "true", "True") else 0
            alvos = (
                ["Arquitetura_Nova", "Arquitetura_Velha"]
                if alvo == "ambas"
                else [alvo]
            )
            resultados = {}
            for arq in alvos:
                if arq not in ESTADO_CONEXAO:
                    continue
                url = f"{ESTADO_CONEXAO[arq]['url']}/api/agente"
                try:
                    req = urllib.request.Request(
                        url,
                        data=json.dumps({"usar_agente": usar_agente}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=5.0) as resp:
                        resultados[arq] = json.loads(resp.read().decode("utf-8"))
                        ESTADO_CONEXAO[arq]["usar_agente"] = usar_agente
                except Exception as e:
                    resultados[arq] = {"ok": False, "erro": str(e)}
            return self._enviar_json(200, {"ok": True, "resultados": resultados})

        if self.path == "/api/config-urls":
            if body.get("url_nova"):
                ESTADO_CONEXAO["Arquitetura_Nova"]["url"] = _normalizar_url(body["url_nova"])
            if body.get("url_velha"):
                ESTADO_CONEXAO["Arquitetura_Velha"]["url"] = _normalizar_url(body["url_velha"])
            return self._enviar_json(200, {"ok": True, "conexoes": ESTADO_CONEXAO})

        return self._enviar_json(404, {"erro": "Rota nao encontrada"})


if __name__ == "__main__":
    inicializar_postgres()
    threading.Thread(target=loop_sincronizacao, daemon=True).start()
    porta = int(os.environ.get("PORT", "9090"))
    server = ThreadingHTTPServer(("0.0.0.0", porta), CentralAPIHandler)
    print(f">>> [Sincronizador Central + API] Rodando em http://0.0.0.0:{porta}/api/dashboard")
    server.serve_forever()

