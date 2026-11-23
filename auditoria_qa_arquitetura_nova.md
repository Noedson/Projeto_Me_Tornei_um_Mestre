# Auditoria de QA: Arquitetura Nova (Django + ChirpStack + Agente IA V4)

**Escopo:** `telemetria/views.py`, `agente/services.py`, `agente/preprocessamento.py`, `agente/management/commands/retreinar_agente.py`, `treinar_agente_v4.py`, `settings.py`, `docker-compose.yml`, `entrypoint.sh`, `monitorar_recursos_docker.py` e a integração com o `sincronizador_central.py`.
**Data:** 19/11/2026. Análise estática do código mais os logs observados nas sessões anteriores.

Severidade: 🔴 Crítico (invalida resultados ou perde dados) · 🟠 Alto · 🟡 Médio · 🔵 Baixo

---

## 🔴 1. A IA não prevê "15 min à frente" na inferência (treino e produção veem dados diferentes)

**Onde:** [treinar_agente_v4.py](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/Arquitetura_Nova/treinar_agente_v4.py#L56-L58) (L56–58, L109) vs. [services.py](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/Arquitetura_Nova/agente/services.py) `avaliar_janela()`

- **Treino:** `df[GASES].resample("1min").mean()`. Cada passo da janela vale **1 minuto**, então `JANELA=30` cobre 30 min e `HORIZONTE=15` fica 15 min à frente.
- **Inferência:** pega as **32 últimas leituras brutas**, sem reamostrar. Com o LWN-Simulator enviando a cada ~5 s:
  - a janela cobre **~2,5 min**, não 30 min;
  - o "horizonte de 15 passos" vira **~75 segundos**, não 15 min.

> [!CAUTION]
> Por isso a afirmação "alerta antecipado em +15 min" (Δt) não vale nas condições atuais. Também explica por que a previsão sempre dá "Boa 99%": o modelo recebe uma janela quase constante.

**Correção:** na inferência, reamostrar para 1 min (`resample("1min").mean()`) usando as últimas ≥32 min de leituras e só então montar as janelas. Assim o pipeline fica igual ao do treino. O mesmo vale para `servico_agente_velha.py`.

---

## 🔴 2. A troca de modo pelo `dt_mediano` muda a feature `CO_media_8h` sem aviso

**Onde:** `services.py`: `modo_teste = APP_TESTE=="1" or dt_mediano <= 20.0`

- Se as leituras chegam a cada ≤20 s (simulador **ou** um ESP32 configurado rápido em produção), a "média de 8 h" passa a ser calculada **só sobre as 32 leituras da janela** (~2,5 min).
- O 8º canal do modelo muda de significado sem nenhum registro, e a classe do IQAr (rotulada pela média de 8 h) deixa de corresponder ao treino.

**Correção:** decidir o modo **apenas** pela flag explícita `APP_TESTE`, e registrar essa decisão no CSV ou SQLite de métricas para documentar na dissertação.

---

## 🔴 3. O hot-reload do retreino não recarrega o servidor web

**Onde:** [retreinar_agente.py](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/Arquitetura_Nova/agente/management/commands/retreinar_agente.py#L245) (L245)

- `python manage.py retreinar_agente` roda em **outro processo**. Nele, `AirQualifyService._instance` é `None`, então `recarregar_modelo()` devolve `False`.
- O `runserver` continua usando o modelo **antigo** em memória. O StatReloader só observa arquivos `.py`, então trocar o `.keras` não dispara recarga.
- O log ainda diz "Zero Downtime", o que é enganoso.

**Correção:** um endpoint interno protegido (ex.: `POST /api/agente/reload`), ou checar o `mtime` de `modelo_iqar.keras` a cada inferência e recarregar quando mudar.

---

## 🔴 4. O rollback do retreino não restaura o `scaler.pkl` e pode restaurar só metade do par modelo/config

**Onde:** `retreinar_agente.py` L146–154, L196–201

- O backup preventivo copia `modelo_iqar.keras` e `config_agente.json`, mas **não copia o `scaler.pkl`**, que o `treinar_agente_v4.py` sobrescreve (L457).
- Se o processo falhar (`returncode != 0`), só o **modelo** é restaurado. O config **não**.
- O resultado possível é modelo antigo + scaler/config novos. As previsões ficam erradas e nenhum erro aparece.

**Correção:** tratar `modelo + scaler + config` como uma unidade só: treinar num diretório temporário e promover os 3 arquivos juntos (rename atômico).

---

## 🟠 5. O gatekeeper pode aprovar com métricas velhas

**Onde:** `retreinar_agente.py` L206–221

- O `metricas_finais.json` da execução **anterior** não é apagado antes do novo treino. Se o V4 falhar depois de gravar o modelo e antes de gravar as métricas, o gatekeeper lê a acurácia antiga.

**Correção:** apagar `metricas_finais.json` antes do treino e conferir um `run_id` ou timestamp dentro do JSON.

---

## 🟠 6. Webhook sem idempotência: duplicatas do LoRaWAN entram em dobro

**Onde:** `telemetria/views.py` (`AirReading.objects.create`) + [models.py](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/Arquitetura_Nova/telemetria/models.py#L15-L33)

- O ChirpStack reenvia quando há timeout ou erro HTTP, e uplinks podem chegar duplicados por vários gateways. Não existe `UNIQUE(sensor, timestamp)` nem checagem de `fCnt`.
- As duplicatas criam `dt = 0` na janela. Isso puxa o `dt_mediano` para baixo (ativa o item 2) e distorce a velocidade e aceleração (`DinamicaTemporal`).

**Correção:** `UniqueConstraint(fields=["sensor","timestamp"])` + `get_or_create`, ou guardar `fCnt` e `deduplicationId` do payload v4.

---

## 🟠 7. Gás ausente vira `0.0` sem aviso

**Onde:** `views.py`: `float(obj.get("CO2_MQ135", 0.0))` e assim por diante

- Se o decoder ou o ESP32 deixar de mandar um gás, ele é gravado como **0 ppm**, um valor físico válido. O autoencoder vai acusar anomalia, ou pior, aprender isso no retreino.

**Correção:** rejeitar (400) ou marcar a leitura como incompleta e pular a inferência. Validar também faixa e `math.isfinite`.

---

## 🟠 8. Erros de servidor respondem 400, e a leitura fica salva pela metade

**Onde:** `views.py`: um `try/except Exception` envolvendo tudo → `400`

- Uma falha do banco, do TensorFlow ou do pandas (ex.: `rolling("8h")` com índice fora de ordem) responde **400 (erro do cliente)**. Para o ChirpStack isso conta como erro definitivo.
- Não há `transaction.atomic()`: a `AirReading` já foi gravada, mas a `AgentPrediction` e a métrica não. A leitura existe sem predição e sem métrica, e a comparação entre cenários perde amostras.

**Correção:** separar erros de validação (400) de erros internos (500 com log); `transaction.atomic()` para leitura + predição; métrica gravada também em caso de falha (`erro_agente=1`).

---

## 🟠 9. Desligar o agente reinicia o `smart_campus_web` e perde leituras

**Onde:** `monitorar_recursos_docker.py` → `docker restart smart_campus_web` quando `usar_agente=0`

- Cada restart leva ~20–30 s (migrations, provisionamento do ChirpStack, carga do TF). Os uplinks que chegam nesse intervalo **falham e não são reenviados** pela integração HTTP.
- No modo desenvolvimento, **qualquer edição de `.py`** também reinicia o servidor (já visto no log: `services.py changed, reloading`).

**Correção:** registrar o downtime e excluir essa janela das estatísticas; ou carregar o TF em um processo/serviço separado (como na Velha) para não precisar reiniciar o Django.

---

## 🟠 10. O monitor conta o simulador como custo da Arquitetura Nova

**Onde:** `monitorar_recursos_docker.py`: `PREFIXOS_CONTAINERS = ("smart_campus_",)`

- O container `smart_campus_lwn_simulator` (perfil `teste`) começa com esse prefixo e entra no `TOTAL_ARQUITETURA`. CPU, RAM e rede do simulador ficam somadas à Nova, mas não à Velha.

**Correção:** excluir explicitamente `smart_campus_lwn_simulator` (lista de exclusão) ou renomear o container para `sim_lwn`.

---

## 🟠 11. Segurança: endpoints destrutivos sem autenticação

| Item | Local | Risco |
|---|---|---|
| `POST /api/backup-reset`, `/api/backup-restore`, `/api/agente` | monitor `:9095` (exposto em `0.0.0.0`) | Qualquer máquina da rede pode zerar o banco ou mudar o cenário no meio do experimento |
| `/var/run/docker.sock` montado no monitor | `docker-compose.yml` | Uma falha no monitor dá controle total do host |
| Webhook `/api/chirpstack/webhook/` sem token | `views.py` (`csrf_exempt`) | Leituras falsas podem ser injetadas |
| `SECRET_KEY` fixa e `DEBUG = True` | [settings.py](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/Arquitetura_Nova/Projeto_Me_Tornei_Um_Mestre/settings.py#L24-L27) | Stack traces e configurações expostas |
| Postgres `5432` publicado com senha padrão | `docker-compose.yml` | Acesso direto ao banco |
| `runserver` em "produção" | `entrypoint.sh` | Servidor de desenvolvimento, não feito para rodar 24/7 |

**Correção mínima:** header `X-Token` compartilhado (variável de ambiente) no webhook e no monitor; publicar `9095` e `5432` só na rede dos experimentos; `gunicorn` + `DEBUG=False` no modo produção.

---

## 🟡 12. O sincronizador pode pular a linha `TOTAL_ARQUITETURA`

**Onde:** `/api/sync?after_ts=...&limit=500` + `sincronizador_central.py`

- Cada coleta grava ~10 linhas com o **mesmo `timestamp`**, e o `TOTAL_ARQUITETURA` é a **última**. Se o `LIMIT 500` cortar no meio de uma coleta, a próxima chamada usa `timestamp > ultimo_ts` e **pula** o resto, inclusive o TOTAL. Isso acontece quando há atraso acumulado (ex.: depois de um resgate de backup ou de uma queda de rede).

**Correção:** usar `timestamp >= ultimo_ts` (o `ON CONFLICT DO NOTHING` já descarta duplicatas), ou paginar por coleta inteira.

---

## 🟡 13. Cooldown compara relógios diferentes

**Onde:** `services.py`: `AgentAlert.timestamp` (`auto_now_add`, relógio do servidor) vs. `ultimo_ts` (relógio do sensor/ChirpStack)

- Com relógio do ESP32 adiantado ou atrasado, ou em replays de simulador, o cooldown de 15 min **nunca dispara** ou **bloqueia para sempre**. A Velha usa só o relógio do sensor, então as duas arquiteturas se comportam de forma diferente.

**Correção:** guardar o `timestamp_sensor` no `AgentAlert` e comparar sempre na mesma base.

---

## 🟡 14. `gap_max_s` diferente entre as arquiteturas

- Nova: padrão **60 s** (`services.py`) · Velha: padrão **900 s** (`servico_agente_velha.py`), a menos que o `config_agente.json` defina.
- Com perda de pacotes LoRa (comum), a Nova suspende a IA (`return None`) com muito mais frequência. O número de predições e alertas deixa de ser comparável.

**Correção:** ler o mesmo valor do `config_agente.json` nas duas, sem padrões diferentes no código.

---

## 🟡 15. As latências da Nova e da Velha medem coisas diferentes

- Nova: `latencia_agente_ms` = consulta ao Postgres + pré-processamento + inferência, dentro do Django.
- Velha: medida dentro do serviço HTTP do agente (sem a ida e volta HTTP `IoT-Agent → agente-ia`).
- Nenhuma das duas mede a latência **de ponta a ponta** (gateway → alerta).

**Sugestão:** registrar `timestamp_sensor → timestamp_alerta` nas duas, usando o mesmo relógio (NTP), e documentar a definição de cada métrica.

---

## 🔵 Itens menores

- **Escrita não atômica do `estado_agente.json`:** uma leitura concorrente pode pegar o JSON pela metade e cair no padrão `USAR_AGENTE` da variável de ambiente, trocando o cenário por um request. Use `write tmp + os.replace`.
- **Threads de métrica sem limite** (`registrar_metrica_leitura`): se o monitor travar, as threads acumulam, e as métricas pendentes se perdem num restart. Use uma fila com 1 worker.
- **`CREATE UNIQUE INDEX` no resgate** (monitor SQLite) falha se o banco ativo já tiver duplicatas, e depois disso o `INSERT` normal do coletor pode lançar `IntegrityError`.
- **Retreino mistura vários sensores** em um único CSV ordenado por tempo, o que corrompe as janelas quando houver mais de um ESP32.
- **Falta índice composto** `(sensor_id, timestamp)` em `AirReading` para a consulta das 32 últimas leituras quando o banco crescer em 30 dias.
- **CPU% do Docker passa de 100%** em máquinas com vários núcleos (vimos 92% somados). O acelerômetro (`max=100`) satura. Normalize por `nproc`.
- **`TIME_ZONE = 'America/Belem'` no Django** vs. `TZ=America/Sao_Paulo` no monitor: o horário é o mesmo hoje (UTC-3), mas vale padronizar.

---

## Prioridade sugerida antes de iniciar os 30 dias

| # | Ação | Impacto na dissertação |
|---|---|---|
| 1 | Reamostrar para 1 min na inferência (Nova e Velha) | Sem isso, o claim "+15 min" fica inválido |
| 2 | Remover a troca automática por `dt_mediano` | Feature consistente com o treino |
| 10 | Excluir o simulador do `TOTAL_ARQUITETURA` | Comparação justa de recursos |
| 6, 14 | Idempotência + `gap_max_s` igual nas duas | Contagem de predições comparável |
| 11 | Token nos endpoints do monitor/webhook | Ninguém altera o experimento por engano |
| 3, 4, 5 | Retreino atômico e reload real | Só se o retreino for usado durante o experimento |
