# Relatório Técnico: Evolução, Validação e Resultados do Agente Inteligente Multi-Task
**Projeto:** Monitoramento Autônomo da Qualidade do Ar (LoRaWAN / Django / Keras)  
**Data:** 08/10/2026  
**Documentação consolidada da sessão de validação e aprimoramento.**

---

## 1. Contexto e Motivação Inicial

O sistema integra sensores físicos de qualidade do ar (MQ-135 e MQ-131 via LoRaWAN/ChirpStack) a uma aplicação Django, com um Agente Inteligente baseado em Rede Neural Recorrente (LSTM Multi-Task) responsável por três funções simultâneas:
1. **Detecção de Anomalias:** Autoencoder LSTM que reconstrói a sequência e detecta desvios pelo erro de reconstrução.
2. **Previsão Temporal (*Forecasting*):** Estima a tendência futura de concentração de gases via predição de delta padronizado.
3. **Classificação do IQAr:** Estima o Índice de Qualidade do Ar (faixas da norma EPA / CONAMA 491/2018 baseadas na média móvel de 8 horas do CO).

---

## 2. Diagnóstico Inicial: Inconsistências Críticas Encontradas

Na auditoria inicial do código, foram identificados gargalos conceituais e de engenharia de software:

1. **Dessincronização de Artefatos:**
   - O serviço `AirQualifyService` falhava ao carregar (`KeyError: 'clip_max'`) devido a arquivos de modelo e configurações herdados de execuções anteriores incompatíveis.
2. **Problemas de Thread Safety no Django:**
   - O carregamento do modelo Keras como *Singleton* em ambiente concorrente (múltiplas requisições simultâneas do Webhook) não continha bloqueio de thread (*Lock*), gerando risco de condição de corrida.
3. **Média Móvel de 8h e Resolução de Norma:**
   - A classificação do IQAr exige o cálculo da média móvel de 8 horas do CO. Avaliar janelas pontuais de sensores sem o histórico de 8 horas distorcia o enquadramento na norma.
4. **Tratamento de Dados Incompletos:**
   - O Webhook substituía valores ausentes por `0.0`, introduzindo ruído severo e disparando falsos alarmes espúrios.

---

## 3. Primeira Rodada de Treino: Análise Crítica e Sincera das Falhas

Após a correção do pipeline básico de código, foi executada a primeira rodada de treino do modelo. Embora a engenharia não tenha quebrado, **a avaliação estatística revelou problemas graves que inviabilizariam o trabalho em uma banca de mestrado**:

### A. Previsão Temporal Pior que a Persistência (*Skill Negativo*)
* As leituras originais ocorriam a cada **5 segundos**. Em 5 segundos, a atmosfera não varia sensivelmente; o sinal varia apenas por ruído de quantização dos sensores MQ.
* A rede LSTM tentou prever o próximo passo ($t+5\text{s}$) e teve um Erro Médio Absoluto (MAE) **26% a 61% maior** do que a linha de base ingênua de persistência ($x_{t+1} = x_t$).

### B. "Falsa" Acurácia de 100% no IQAr (Vício de Amostragem)
* O particionamento puramente cronológico (70% treino, 15% validação, 15% teste) alocou todas as ocorrências de ar "Ruim" no início e meio da série temporal.
* O conjunto de teste continha **0 amostras da classe "Ruim"** (96,5% de ar Moderado e 3,5% de ar Bom).
* A acurácia de 100% e o Recall de 0.000 eram uma anomalia estatística: a rede nunca foi testada sob condições de risco real.

### C. Alarme de Anomalia "Morto" (*Dead Alarm*)
* O limiar de reconstrução foi fixado no percentil 99 da validação (`0.17666`).
* Como os erros médios do modelo eram da ordem de `0.02` a `0.04`, mesmo injetando anomalias sintéticas (picos de +0.1), o erro nunca ultrapassava o corte.
* Resultado: **Precisão = 0.000 e Recall = 0.000**. O alarme nunca dispararia em produção.

### D. Overfitting Imediato
* O treinamento foi interrompido na Época 6 porque a menor perda de validação foi obtida logo na Época 1, indicando falta de generalização decorrente da alta frequência das amostras.

---

## 4. O Novo Pipeline Científico: As 5 Etapas Implementadas

Para solucionar as 4 causas-raiz, foi implementada uma reestruturação metodológica completa:

```
[Dados Brutos a cada ~5s]
           │
           ▼
1. Reamostragem (1 minuto) ──► Filtra ruído elétrico de alta frequência
           │
           ▼
2. Horizonte de 15 Minutos ──► Previsão em escala de tempo útil (dinâmica física real)
           │
           ▼
3. Blocked Time-Series Split ──► Garante classes Boa, Moderada e Ruim no Teste
           │
           ▼
4. Regularização da Rede ──► Bidirectional LSTM reduzido + Dropout contra overfitting
           │
           ▼
5. Calibração F1 do Limiar ──► Ponto de corte ótimo equilibrando falso alarme e detecção
```

### Detalhes das Modificações:

1. **Reamostragem (*Downsampling*) para 1 minuto:**
   - 46.109 registros limpos e agregados via média de 1 minuto com interpolação linear para lacunas curtas ($\le 3$ min).
2. **Horizonte de Previsão de 15 Minutos:**
   - Janela de entrada: **30 minutos de histórico** (`JANELA = 30`).
   - Alvo da previsão: **15 minutos à frente** (`HORIZONTE = 15`).
3. **Particionamento em Blocos Semanais (*Blocked Time Split*):**
   - A série de 223 dias foi particionada em blocos semanais preservando a ordem cronológica dentro de cada bloco.
   - O conjunto de teste passou a ter **2.758 amostras de ar Bom, 2.226 de Moderado e 967 de Ruim**.
4. **Calibração Ótima do Limiar de Anomalia via $F_1$-Score:**
   - O limiar passou a ser calibrado por varredura de $F_1$-Score na base de validação, resultando em um corte ótimo de **`0.04935`**.

---

## 5. Resultados Finais e Validação Experimental

### 5.1. Previsão Temporal (15 Minutos à Frente): Superação da Persistência

Ao prever 15 minutos à frente, a dinâmica de dispersão química supera o ruído e o LSTM atinge **Skill Score positivo** em praticamente todos os gases:

| Gás / Sensor | MAE Modelo (LSTM) | MAE Persistência | Skill Score (*Ganho*) |
| :--- | :---: | :---: | :---: |
| **CO_MQ135** | **11.31 ppm** | **11.99 ppm** | **+5.65% (Superou)** |
| **CO2_MQ135** | **1.39** | **1.43** | **+2.63% (Superou)** |
| **MH4_MQ135** | **1.36** | **1.38** | **+1.55% (Superou)** |
| **Alcool_MQ135** | **0.99** | **1.03** | **+3.13% (Superou)** |
| **Toluen_MQ135** | **0.64** | **0.65** | **+2.45% (Superou)** |
| **Aceton_MQ135** | **0.48** | **0.49** | **+1.93% (Superou)** |
| **O3_MQ131** | **1.07** | **1.07** | **-0.03% (Empate)** |

### 5.2. Classificação de Risco do IQAr (15 Minutos à Frente)

Avaliado no conjunto de teste independente com **5.951 janelas**:

* **$F_1$-Score Macro:** **0.984** (Modelo) vs **0.981** (Persistência)
* **Acurácia Balanceada:** **0.983** (Modelo) vs **0.978** (Persistência)

**Métricas detalhadas por classe:**
* **Classe "Boa" (2.758 amostras):** Precisão: 99,4% | Recall: 98,4% | F1: 98,9%
* **Classe "Moderada" (2.226 amostras):** Precisão: 97,2% | Recall: 99,2% | F1: 98,2%
* **Classe "Ruim" - Crítica (967 amostras):** **Precisão: 99,2% | Recall: 97,2% | F1: 98,2%**

> **Resultado Prático:** De 967 ocorrências de ar deteriorado no teste, o agente alertou **940 eventos com 15 minutos de antecedência**, com apenas 0,8% de alarmes falsos.

### 5.3. Detecção de Anomalias (Autoencoder Calibrado)

Com o limiar calibrado em `0.04935`:
* **Deriva Lenta (+0.2 - descalibração do sensor):**
  - **AUC-ROC:** 0.945 | **Precisão:** 89,7% | **Recall:** 99,9% | **F1:** 94,5%
* **Deriva Severa (+0.3):**
  - **AUC-ROC:** 0.981 | **Precisão:** 89,8% | **Recall:** 100,0% | **F1:** 94,6%
* **Picos Sintéticos (+0.2 a +0.3):**
  - **AUC-ROC:** 0.719 a 0.805 | **Precisão:** 63,2% a 74,6% | **Recall:** 19,6% a 33,5%

---

## 6. Sincronização da Aplicação Django

1. **`telemetria/models.py`:**
   - Adicionado modelo `AgentPrediction` para rastreabilidade de todas as predições e erros de reconstrução.
   - Corrigido `auto_now_add=True` no `AgentAlert`.
2. **`telemetria/views.py`:**
   - Ajustado para buscar 40 leituras históricas do sensor para atender à janela de 30 minutos mais janelas de confirmação.
   - Descarte limpo de payloads vazios de CO sem preenchimento artificial de zeros.
3. **`agente/services.py`:**
   - Transformado em Singleton *Thread-Safe* com `threading.Lock`.
   - Busca sob demanda do histórico de 8 horas para cálculo exato da média móvel de CO.
   - *Cooldown* de 15 minutos entre alertas idênticos para evitar poluição visual no painel.
4. **`requirements.txt`:**
   - Exportação completa e congelada de todas as dependências do ambiente virtual Python.

---

## 7. Arquivos e Artefatos Gerados

* **Modelo Serializado:** `agente/modelo_iqar.keras`
* **Normalizador:** `agente/scaler.pkl`
* **Configuração Calibrada:** `agente/config_agente.json`
* **Relatório JSON de Métricas:** `agente/metricas_finais.json`
* **Histórico das Épocas:** `agente/historico_treinamento.csv`
* **Gráficos em Alta Resolução (300 DPI):**
  - `agente/graficos/1_curva_aprendizado_loss.png`
  - `agente/graficos/2_previsao_temporal_real_vs_pred.png`
  - `agente/graficos/3_distribuicao_erros_anomalia.png`
  - `agente/graficos/4_matriz_confusao_iqar.png`
  - `agente/graficos/5_sensibilidade_anomalia.png`

---

## 8. Como Executar

### Para rodar o servidor Django:
```bash
python manage.py runserver
```

### Para retreinar o modelo no futuro:
```bash
python treinar_agente.py
```
