# Registro Completo da Sessão: Monitoramento Computacional das Duas Arquiteturas, Desenho Experimental (30 Dias) e Estrutura do Dashboard Central

**Projeto:** Monitoramento Autônomo da Qualidade do Ar com IA Multi-Task (LoRaWAN / ChirpStack v4 / Django / FIWARE / Keras)  
**Data da Sessão:** 12/11/2026  
**Status:** Monitoramento Dockerizado (SQLite + CSV + API Sync) e flag `USAR_AGENTE` implementados nas duas arquiteturas; Banco Central PostgreSQL + Sincronizador e estrutura base React + Vite Dockerizados prontos para a construção final do `src/App.tsx`.

---

## 1. Como Monitorar Recursos Computacionais em Produção e nas Duas Arquiteturas

### Perguntas Iniciais (Usuário):
> *"na produção, como podemos monitorar os recursos computacionais?"*  
> *"a partir dessas anotações, o que podemos monitorar nas duas arquiteturas?"*

**Anotações de Reunião Analisadas:**
* **Agente inteligente:** pesquisar sobre aprendizado não supervisionado; aviso sobre a poluição presente; qual seria o tempo de aviso com agente e sem o agente; avaliar o uso de CPU sem o agente e com agente; medir o tempo, memória, CPU, rede; colocar as duas arquiteturas no Docker e medir o custo computacional das duas (4 cenários: dois com agente e dois sem o agente); tempo entre detectar, mandar o aviso e antecipar o aviso.
* **Bugs anotados:** gráfico de predição invertida no tempo (pendente para próxima etapa).

### Síntese das Métricas Definidas para a Dissertação:
1. **Recursos Computacionais no Docker (`docker stats`):**
   * **CPU (`%`):** Consumo basal e pico durante a inferência do Agente V4.
   * **Memória RAM (`MB` / `GB` e `%`):** Memória total da stack e diferença com/sem o modelo TensorFlow/Keras carregado.
   * **Rede (`Net RX / TX` acumulado e Velocidade Instantânea `KB/s` / `MB/s`):** Volume e taxa de dados trafegados internamente entre os containers.
   * **Disco (`Block Read / Write`):** Volume de leitura e escrita em disco (PostgreSQL vs. MongoDB + Postgres).
2. **Métricas de Latência Operacional ($\text{ms}$):**
   * `latencia_total_ms`: Tempo total desde o recebimento do pacote HTTP até a persistência e geração do alerta.
   * `latencia_agente_ms`: Tempo exclusivo gasto pela execução do Agente Inteligente V4 (pré-processamento da janela + inferência Multi-Task Bi-LSTM/Autoencoder).
3. **Métricas de Autonomia e Antecipação do Aviso ($\Delta t_{\text{antecipação}}$):**
   * **Sem Agente (Reativo / Poluição Presente):** Só avisa quando o sensor físico atinge o limiar crítico no instante $T_{\text{reativo}}$ ($\text{antecipação} = 0\text{ min}$).
   * **Com Agente (Proativo / Preditivo 15 min à frente + Autoencoder):** Emite o alerta no instante $T_{\text{agente}}$, antes da poluição atingir o nível crítico:
     $$\Delta t_{\text{antecipação}} = T_{\text{reativo}} - T_{\text{agente}}$$

---

## 2. Desenho Experimental: 4 Cenários em 2 Máquinas ao Longo de 30 Dias (15 + 15 Dias)

### Perguntas (Usuário):
> *"podemos adaptar o agente (treinar_agente_v4.py) para as duas arquiteturas? (na minha cabeça com agente é a arquitetura nova e sem agente a arquitetura velha)."*  
> *"nesse caso, seria interessante colocar em 4 computadores?"*  
> *"suponhamos que usaremos o esp32 com os sensores, faz sentido usar 4 computadores?"*  
> *"reduziremos de 4 computadores para 2, em um colocaremos a arquitetura velha e no outro a nova, na primeira parte do experimento, rodaremos sem o agente nas duas, e na segunda parte, as mesmas arquiteturas com o agente, compararemos as vantagens e as desvantagens. (primeira parte com 15 primeiros dias do mês e a segunda parte nos últimos 15 dias)."*

### Decisões Metodológicas:
1. **Por que testar o Agente nas duas arquiteturas (Experimento Fatorial $2 \times 2$):**
   Permite isolar na dissertação o que é ganho/custo da **Arquitetura de Software** (Django/PostgreSQL vs. Node-RED/Proxy/FIWARE/MongoDB) e o que é ganho/custo da **Inteligência Artificial (Agente V4)**:
   * Cenário 1: Arquitetura Velha — Sem Agente (`USAR_AGENTE=0`)
   * Cenário 2: Arquitetura Velha — Com Agente (`USAR_AGENTE=1`)
   * Cenário 3: Arquitetura Nova — Sem Agente (`USAR_AGENTE=0`)
   * Cenário 4: Arquitetura Nova — Com Agente (`USAR_AGENTE=1`)
2. **Divisão em 2 Fases de 15 Dias com 2 Máquinas Físicas + 3ª Máquina (Monitoramento):**
   * **Quinzena 1 (Primeiros 15 dias):** Máquina 1 (Arquitetura Velha) e Máquina 2 (Arquitetura Nova) rodando simultaneamente **Sem Agente (`USAR_AGENTE=0`)**.
   * **Quinzena 2 (Últimos 15 dias):** Máquina 1 (Arquitetura Velha) e Máquina 2 (Arquitetura Nova) rodando simultaneamente **Com Agente (`USAR_AGENTE=1`)**.
   * Mesmo durante a Quinzena 2 (Com Agente), o código continua registrando em paralelo o instante em que o alerta reativo (`alerta_reativo_presente`) disparou, permitindo calcular no mesmo evento físico real a antecipação exata $\Delta t = T_{\text{reativo}} - T_{\text{agente}}$.

---

## 3. Descoberta Experimental Durante os Testes: Por que a Arquitetura Velha Consome ~100 KB/s a Mais de Rede?

### Observação (Usuário):
> *"percebo que a arquitetura velha consome mais banda (aproximadamente 100kbps) é por causa dos numeros de containers? o que isso pode impactar?"*

### Explicação Técnica (Amplificação de Tráfego Interno):
* Na **Arquitetura Nova**, 1 leitura LoRaWAN gera **1 único POST HTTP** (`ChirpStack -> Django`) e **1 único INSERT SQL** (`Django -> PostgreSQL`) contendo todos os 7 gases na mesma linha.
* Na **Arquitetura Velha**, 1 leitura passa por `ChirpStack -> Node-RED -> Proxy TS`, e dentro do `IotControllers.ts` o trecho `Promise.all(formattedData.map(sendDataAgent))` divide 1 leitura em **9 requisições HTTP separadas** (7 gases + Temperatura + Umidade) para o `FIWARE IoT-Agent`, que por sua vez consulta o `MongoDB` e envia 9 requisições NGSI-v2 ao `FIWARE Orion`, que notifica o `FIWARE Cygnus` e grava novamente no `MongoDB` — transformando **1 pacote do sensor em mais de 35 transações internas de rede**.
* **Impactos documentados para a dissertação:** Maior latência ponta a ponta, gargalo de escalabilidade quando o número de sensores ESP32 crescer, desperdício de CPU com serialização HTTP/JSON e maior superfície de falha.

---

## 4. Arquitetura de Persistência e "Repique" (Store-and-Forward) para o Dashboard Central

### Decisão de Arquitetura (Usuário):
> *"o que acha de usar o banco de dados para armazenar as metricas?"*  
> *"podemos ter um terceiro banco na terceira maquina, que vai 'repicar' os sqlite da arquitetura?"*  
> *"antes, vamos dockerizar o monitoramento (algumas revistas querem reproduzir o experimento)."*

### Solução Implementada:
1. **Monitoramento 100% Dockerizado nas Duas Arquiteturas (`monitor_recursos_nova` e `monitor_recursos_velha`):**
   * Criados `Dockerfile.monitor` (`python:3.12-alpine` + `docker-cli`) montando `/var/run/docker.sock:/var/run/docker.sock`.
   * Os nomes dos containers (`monitor_recursos_nova` e `monitor_recursos_velha`) não usam os prefixos `smart_campus_` nem `velha_`, garantindo que o consumo do próprio monitor **nunca contamine** a linha `TOTAL_ARQUITETURA`.
   * Cada arquitetura salva localmente a cada 15 segundos tanto em CSV (`monitoramento/recursos_docker.csv`) quanto em um banco **SQLite local em modo WAL** (`monitoramento/metricas_experimento.db`), com conversão automática de unidades (`B`, `KB`, `MB`, `GB` e velocidade `B/s`, `KB/s`, `MB/s`).
   * Expõe uma API HTTP leve (porta `9095` na Nova e `9096` na Velha) com:
     * `GET /api/sync?after_id=...`: entrega incrementalmente apenas os registros novos para a 3ª máquina.
     * `POST /api/agente`: altera `monitoramento/estado_agente.json` (`{"usar_agente": 1}` ou `0`), ligando/desligando o Agente em tempo real nas duas arquiteturas.
2. **3ª Máquina (`Código/Monitoramento/Dashboard_Esperimento`):**
   * **`db-central` (`postgres:16-alpine` na porta `5435`):** Banco PostgreSQL Central isolado que armazena os dados unificados das duas arquiteturas (`recursos_central` e `leituras_central`).
   * **`sync-api` (`sincronizador_central.py` na porta `9090`):** Faz o "repique" (sincronização incremental a cada 5s) puxando os SQLites da Máquina 1 (`9096`) e Máquina 2 (`9095`), calcula as médias comparativas dos 4 cenários via SQL e repassa o comando de Ligar/Desligar o Agente.
   * **`dashboard` (React 19 + Vite 8 + Recharts + Lucide na porta `5173`):** Containerizado com `Dockerfile` (`node:24-alpine`) e *Hot-Reload* via `vite.config.ts`.

---

## 5. Arquivos Criados e Modificados Nesta Sessão

### Arquitetura Nova (`Código/Arquitetura_Nova/`)
* `Dockerfile.monitor` *(Novo)*
* `monitorar_recursos_docker.py` *(Novo — Coletor Docker + Conversão KB/MB/GB + Velocidade de Rede + SQLite + API `/api/sync` e `/api/agente` na porta `9095`)*
* `telemetria/views.py` *(Atualizado — Leitura dinâmica de `estado_agente.json` / `USAR_AGENTE`, medição de `latencia_total_ms` e `latencia_agente_ms`, registro em `monitoramento/metricas_processamento_leituras.csv`)*
* `docker-compose.yml` *(Atualizado — Variável `USAR_AGENTE` e serviço `monitor-recursos` na porta `9095`)*
* `iniciar_docker.ps1` e `parar_docker.ps1` *(Atualizados — Flags `-a`/`--com-agente` e `-sa`/`--sem-agente` e aba de logs do `monitor_recursos_nova`)*

### Arquitetura Velha (`Código/Arquitetura_Velha/`)
* `Dockerfile.monitor` *(Novo)*
* `monitorar_recursos_docker.py` *(Novo — Coletor Docker + Conversão KB/MB/GB + Velocidade de Rede + SQLite + API `/api/sync` e `/api/agente` na porta `9096`)*
* `servico_agente_velha.py` *(Novo — Serviço HTTP na porta `5000` que carrega o mesmo modelo `modelo_iqar.keras`, `scaler.pkl` e `preprocessamento.py` da Arquitetura Nova quando `USAR_AGENTE=1`)*
* `no-commenter-project/mqda/iot-fiware/tutorials.IoT-Agent/src/controllers/IotControllers.ts` *(Atualizado — Suporte a `USAR_AGENTE` via `estado_agente.json`, chamada ao `velha_agente_ia:5000/avaliar` e gravação de `metricas_processamento_leituras.csv`)*
* `nodered_data/flows.json` *(Atualizado — Preservação do campo `time` do sensor)*
* `docker-compose.yml` *(Atualizado — Serviços `agente-ia` e `monitor-recursos` na porta `9096`)*
* `iniciar_docker.ps1` e `parar_docker.ps1` *(Atualizados — Flags `-a`/`--com-agente` e `-sa`/`--sem-agente`)*

### Monitoramento Central — 3ª Máquina (`Código/Monitoramento/Dashboard_Esperimento/`)
* `Dockerfile` *(Novo — Container React + Vite + Recharts + Lucide)*
* `Dockerfile.sync` *(Novo — Container Python + `psycopg2-binary`)*
* `sincronizador_central.py` *(Novo — Repique incremental dos SQLites para o PostgreSQL Central + API `/api/dashboard` e `/api/controle-agente` na porta `9090`)*
* `docker-compose.yml` *(Novo — Orquestra `db-central`, `sync-api` e `dashboard`)*
* `vite.config.ts` *(Atualizado — `host: true`, `port: 5173`, `usePolling: true`)*

---

## 6. Próximos Passos (Para Quando Retomar)
1. Construir a interface visual completa em `Código/Monitoramento/Dashboard_Esperimento/src/App.tsx` consumindo `http://localhost:9090/api/dashboard` e `POST http://localhost:9090/api/controle-agente`.
2. Verificar os dois itens restantes da anotação inicial:
   * **Bug:** Gráfico de predição invertida no tempo.
   * **Pesquisa/Detalhamento:** Destacar o papel do aprendizado não supervisionado (Autoencoder / erro de reconstrução sem rótulo prévio de anomalia) na escrita e nos gráficos.


---

## 7. Atualização da Sessão (13/11/2026) — Frontend Completo e Tempo Real

### 1. Correções nos Coletores e Sincronizador
* **`Código/Arquitetura_Nova/monitorar_recursos_docker.py`:**
  * Removida importação acidental `from django.utils.log import log_message` que impedia o container Python Alpine de iniciar.
  * Alterado `--intervalo` padrão de `15s` para `5s` (em ambos os coletores: Nova e Velha).
  * Substituído `PRAGMA journal_mode=WAL` por `PRAGMA journal_mode=DELETE` com `DB_LOCK = threading.Lock()` e `timeout=30.0` (em ambos os coletores), resolvendo `sqlite3.OperationalError: disk I/O error` em volumes bind-mount do Windows no Docker.
* **`Código/Monitoramento/Dashboard_Esperimento/sincronizador_central.py`:**
  * Loop de sincronização acelerado para `1s`.
  * `GET /api/dashboard?janela=...` agora suporta janelas `5m`, `1h`, `24h`, `7d` e `15d` (com agregação via `date_bin` no PostgreSQL para manter os gráficos leves em históricos longos) e retorna `atual` (última amostra instantânea).
  * Adicionado `_normalizar_url` em `POST /api/config-urls` para completar `http://` automaticamente e converter `localhost`/`127.0.0.1` em `host.docker.internal` dentro do container.

### 2. Dashboard React (`Código/Monitoramento/Dashboard_Esperimento/`)
* **`src/components/Acelerometro.tsx` (Novo):** Velocímetros/acelerômetros SVG animados em tempo real para **CPU (%)**, **RAM**, **Rede RX** e **Rede TX** nos cards das 2 máquinas, zerando automaticamente para `--` quando a máquina fica Offline.
* **`src/App.tsx` e `src/App.css`:**
  * Polling a cada `2s` com indicador `🟢 Ao vivo` e data/hora em formato `pt-BR`.
  * Conversão automática de unidades (`KB`/`MB`/`GB` e `B/s`/`KB/s`/`MB/s`/`GB/s`) nos acelerômetros, tabelas e gráficos (eixo Y + Tooltip), com `white-space: nowrap` e `overflow-x: auto` (`.tabela-scroll`) nas tabelas.
  * **3 Gráficos Comparativos Diretos (Velha vs. Nova)** para CPU, RAM e Rede RX, exibidos automaticamente quando ambas as arquiteturas estão online simultaneamente.
  * **Marcadores Verticais (`<ReferenceLine>`)** indicando o ponto exato em que o Agente IA é ligado (`🤖 Agente ON`) ou desligado (`⚡ Agente OFF`), posicionados à direita da linha (`insideTopLeft`) com alternância vertical (`dy`).
  * **Painel de Configuração de IPs** na interface (`POST /api/config-urls`) e exibição do endpoint atual nos cards.
  * **Painel de Progresso do Experimento (4 Cenários)** com barra de progresso rumo aos 15 dias por etapa (`259.200` amostras a `5s`), além de **badges coloridas** na tabela de últimas leituras destacando alertas antecipados (`⚡🤖 Antecipado (+15m)`).
  * **Exportação:** botões para baixar **Excel (`.xlsx`)** com 2 abas separadas (`Arquitetura Velha` e `Arquitetura Nova`) tanto para o **Histórico** quanto para o **Resumo**, além de botão **`📷 PNG`** (2× resolução) em cada um dos 7 gráficos.
* **`package.json`:** adicionada dependência `xlsx` para geração das planilhas multi-abas no navegador.

### 3. Próximos Passos Pendentes
* Verificar os dois itens restantes da anotação inicial:
  * **Bug:** Gráfico de predição invertida no tempo.
  * **Pesquisa/Detalhamento:** Destacar o papel do aprendizado não supervisionado (Autoencoder / erro de reconstrução sem rótulo prévio de anomalia) na escrita e nos gráficos.

---

## 8. Atualização Final da Sessão (13/11/2026) — Rigor Estatístico e Limpeza de Memória

* **Alinhamento dos Marcadores ON/OFF (`src/App.tsx`):**
  * Alterado `position: 'insideTopRight'` para `position: 'insideTopLeft'` com alternância vertical (`dy: 0` / `14`), posicionando o rótulo à direita da linha tracejada (exatamente onde o novo estado passa a valer) e evitando sobreposição.
* **Métricas Estatísticas Robustas (`sincronizador_central.py` e `src/App.tsx`):**
  * Adicionados **Mediana (P50)** (`PERCENTILE_CONT(0.5)`), **Percentil 95 (P95)** (`PERCENTILE_CONT(0.95)`) e **Desvio Padrão (`± DP`)** (`COALESCE(STDDEV_SAMP(cpu_percent), 0)`) na tabela `Resumo Comparativo dos 4 Cenários` e no Excel (`.xlsx`) exportado, permitindo comprovar estatisticamente que a diferença de CPU com o Agente IA não é apenas um pico isolado.
* **Liberação de Memória RAM ao Desligar na Arquitetura Nova (`Arquitetura_Nova/monitorar_recursos_docker.py`):**
  * Ao receber `usar_agente = 0` em `POST /api/agente`, além de atualizar `estado_agente.json`, o monitor dispara `docker restart smart_campus_web` em segundo plano (`subprocess.Popen`) para descarregar TensorFlow/Keras da RAM do processo Django imediatamente.
* **Observação Experimental de RAM:**
  * Medido no gráfico ao vivo da Arquitetura Velha um degrau de **~250 a 300 MB** ao ligar/desligar o container `velha_agente_ia` (custo real do Agente IA em RAM), sobre uma base de **~2,4 a 2,7 GB** da própria pilha FIWARE + Node-RED + MongoDB.
