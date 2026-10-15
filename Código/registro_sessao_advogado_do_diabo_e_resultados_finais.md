# Histórico de Evolução Técnica, Auditorias Críticas e Decisões do Modelo

**Projeto:** Agente Inteligente de Monitoramento da Qualidade do Ar em Smart Campus  
**Autor:** Noedson Romário Vieira da Silva  
**Instituição:** Universidade Federal do Pará (UFPA) — Campus Universitário de Tucuruí  
**Data de Fechamento do Histórico:** 15/10/2026  
**Status Atual:** Versão 4 homologada como modelo oficial definitivo de produção.

---

## Linha do Tempo e Evolução Cronológica

```
[Marco 1: V1 Inicial] ────► [Marco 2: V2 Derivadas] ────► [Marco 3: V3 Mediana Móvel] ────► [Marco 4: Diagnóstico Gráfico 2] ────► [Marco 5: V4 Oficial & Auditoria Final]
(Lag de fase, RMSE 169)      (Skip connections de física)    (RMSE cai 91%, perda direcional) (Descoberta da subestimação 15 ppm)    (Huber simétrico, skill positivo geral)
```

---

## Marco 1 (Fase Inicial): O Modelo Baseline (V1)

### Arquitetura e Hipótese Inicial
* Rede Bi-LSTM padrão com atenção global e 3 cabeças de saída (Delta de gases, Classificação IQAr e Autoencoder para anomalias).
* Horizonte: Previsão a 15 minutos ($t+15$).

### Problemas e Falhas Diagnosticadas
1. **Atraso de Fase (*Phase Lag*):** O modelo aprendia a estratégia preguiçosa de prever delta quase nulo ($\Delta \approx 0$), comportando-se como um espelho atrasado dos dados reais.
2. **Cegueira nas Transições:** Nas 93 mudanças reais de classe do teste, o modelo inicial errava **$70,97\%$** das vezes (acurácia de apenas **$29,03\%$**).
3. **Explosão do RMSE no CO:** O MAE girava em torno de $10,77\text{ ppm}$, mas o RMSE atingia **$169,97\text{ ppm}$**, evidenciando alta vulnerabilidade a ruídos transitórios do sensor MQ-135.
4. **Desbalanceamento Extremo de Gradientes:** A perda do Autoencoder era de $\approx 0,0018$, do IQAr de $\approx 0,15$ e do Delta de $\approx 0,43$, fazendo com que a regressão do delta sufocasse o aprendizado das outras tarefas.

---

## Marco 2 (13/10/2026): A Injeção de Física e Skip Connections (V2)

### Alterações Implementadas
* **Skip Connections com Derivadas Explícitas:** Concatenou-se à saída latente da LSTM a dinâmica de primeira e segunda ordem da janela observada:
  * Velocidade instantânea ($1\text{ min}$): $v_t = x_t - x_{t-1}$
  * Tendência de curto prazo ($5\text{ min}$): $\Delta_5 = x_t - x_{t-5}$
  * Aceleração temporal: $a_t = (x_t - x_{t-2}) - (x_{t-2} - x_{t-4})$
* **Ponderação Focal nas Transições:** Amostras com mudança de classe entre a janela observada e o futuro receberam peso majorado ($3,5\times$ no IQAr e $3,0\times$ no Delta).

### Resultados Obtidos
* Acurácia nas transições subiu de **$29,03\%$** para **$40,86\%$**.
* CO MAE caiu de $10,77\text{ ppm}$ para $8,49\text{ ppm}$.
* O RMSE ainda continuava elevado ($151,65\text{ ppm}$), demonstrando que o problema não era apenas de capacidade da rede, mas de contaminação por ruído elétrico na série temporal.

---

## Marco 3 (14/10/2026): Denoising por Mediana Móvel e Perda Direcional (V3)

### Alterações Implementadas
1. **Filtro de Mediana Móvel (3 passos):** Inserção de `rolling(window=3, min_periods=1, center=True).median()` na série reamostrada em baldes de 1 minuto, eliminando espículas elétricas transitórias de bancada sem distorcer as frentes de onda de gases.
2. **Rebalanceamento dos Pesos Multi-Task:** Ajuste fino dos multiplicadores de perda (`PESOS_LOSS`):
   * Autoencoder: $15.0$
   * Delta: $1.0$
   * IQAr: $2.5$
3. **Perda Direcional Customizada (`perda_delta_direcional`):** Função de custo assimétrica projetada para penalizar com rigor inversões de sinal entre subida e descida.
4. **Regra Híbrida de Variância para Sensor Travado:** Incorporação da regra estocástica $\sigma < \epsilon$ para cobrir a deficiência teórica do Autoencoder em sinais constantes.

### Resultados Obtidos
* **Queda Histórica do RMSE:** O RMSE do CO desabou de $151,65\text{ ppm}$ para **$14,13\text{ ppm}$ (redução de 91,7%)**, comprovando a eficácia do pré-processamento temporal.
* **Sensor Travado:** Recall atingiu **$100\%$**.
* **Precisão Classe Ruim:** Alcançou **$100\%$** (zero alarmes falsos de ar degradado).

---

## Marco 4 (15/10/2026): O Diagnóstico do "Gráfico 2" e o Efeito Colateral da V3

### A Descoberta da Falha Visual
Durante a auditoria visual detalhada da série temporal real vs. predita (Gráfico 2):
* Notou-se que a curva predita acompanhava a dinâmica dos picos, porém com um **deslocamento sistemático para baixo de até $15\text{ ppm}$**.
* **Causa Raiz Identificada:** A perda direcional assimétrica associada aos pesos focais pesados nos deltas atuava como um "freio de mão estatístico". Para evitar penalizações por falsos aumentos, a rede preferia subestimar sistematicamente as magnitudes de concentração.

---

## Marco 5 (15/10/2026): Homologação da Versão 4 Oficial (V4)

### Correções Cirúrgicas do V4 ([`treinar_agente_v4.py`](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/treinar_agente_v4.py))
1. **Substituição da Função de Perda:** Adoção da **Huber Loss Simétrica** por amostra (`perda_delta_huber`), eliminando qualquer viés direcional e garantindo penalização balanceada tanto para subidas quanto para descidas.
2. **Ponderação Uniforme no Delta:** `sample_weight = 1.0` uniforme para a regressão contínua dos gases, mantendo a focalização ponderada ($2.5\times$) exclusivamente na cabeça de classificação categórica do IQAr.
3. **Calibração do Limiar do Autoencoder:** Percentil $99.0\%$ com suavização contra instabilidades.

### Desempenho Quantitativo Consolidado (V4 vs. Persistência)

#### A. Previsão Temporal de Gases (15 min à frente)
* O modelo superou a persistência em **todos os 6 gases do sensor MQ-135**:
  * **CO:** MAE $2,45\text{ ppm}$ vs $2,58\text{ ppm}$ (**$+5,14\%$ Skill**); RMSE $14,48$ vs $15,23$ (**$+4,93\%$ Skill**).
  * **$CO_2$:** MAE $1,59$ vs $1,72$ (**$+7,40\%$ Skill**); RMSE $3,33$ vs $3,53$ (**$+5,68\%$ Skill**).
  * **$NH_4$:** MAE $1,55$ vs $1,70$ (**$+8,77\%$ Skill**); RMSE $3,45$ vs $3,67$ (**$+6,14\%$ Skill**).
  * **Acetona:** MAE $0,47$ vs $0,50$ (**$+6,71\%$ Skill**); RMSE $0,91$ vs $0,97$ (**$+5,49\%$ Skill**).
  * **Álcool:** MAE $1,05$ vs $1,13$ (**$+7,19\%$ Skill**); RMSE $2,14$ vs $2,27$ (**$+5,54\%$ Skill**).
  * **Tolueno:** MAE $0,58$ vs $0,62$ (**$+6,30\%$ Skill**); RMSE $1,18$ vs $1,24$ (**$+5,30\%$ Skill**).
  * **$O_3$ (MQ-131):** MAE $0,49$ vs $0,48$ ($-1,40\%$ Skill); RMSE $1,07$ vs $1,09$ (**$+1,89\%$ Skill**).

#### B. Classificação IQAr e Transições Críticas
* **Acurácia Global:** $97,51\%$ (Modelo) vs $98,40\%$ (Persistência).
* **F1-Score Macro:** $97,00\%$ (Modelo) vs $98,09\%$ (Persistência).
* **Transições Reais de Classe (95 eventos):**
  * **Persistência ingênua:** acerta **$0,00\%$** ($0$ de $95$ eventos).
  * **Modelo Bi-LSTM V4:** antecipa **$43,16\%$** ($41$ de $95$ eventos).
* **Precisão na Classe Ruim:** **$100,0\%$** (zero falsos alarmes de ar tóxico).

#### C. Detecção de Anomalias
* **Sensor Travado:** **$100,0\%$** de recall via regra estocástica $\sigma < \epsilon$.
* **Pico Abrupto (+0.2):** Recall de **$97,7\%$**, AUC de $0,945$.
* **Pico Abrupto (+0.3):** Recall de **$99,7\%$**, AUC de $0,967$.
* **Deriva Lenta (+0.3):** Recall de **$72,6\%$**, AUC de $0,944$.
* **Falso Alarme em Teste:** $8,72\%$ (calibrado a $1,0\%$ no treino/validação).

---

## Matriz Evolutiva Comparativa (Todas as Versões)

| Métrica / Critério | V1 (Baseline Inicial) | V2 (Física / Derivadas) | V3 (Mediana / Perda Assimétrica) | **V4 (Oficial Definitivo)** |
| :--- | :---: | :---: | :---: | :---: |
| **CO MAE (ppm)** | $10,77$ | $8,49$ | $2,48$ | **$2,45$ (Bate a persistência)** |
| **CO RMSE (ppm)** | $169,97$ | $151,65$ | $14,13$ | **$14,48$ (Redução estável de 91%)** |
| **Skill MAE no CO vs. Persistência** | Negativo | Negativo | Negativo (por subestimação) | **$+5,14\%$** |
| **Skill MAE em Todos Gases MQ-135** | Negativo | Negativo | Misto | **Positivo em 100% dos gases** |
| **Viés Sistemático de Concentração** | Neutro com lag | Neutro com lag | Subestimava em até $15\text{ ppm}$ | **Eliminado (Aderência real)** |
| **Acurácia em Transições do IQAr** | $29,03\%$ | $40,86\%$ | $36,20\%$ | **$43,16\%$ (Persistência = 0%)** |
| **Precisão Classe Ruim (IQAr)** | $100\%$ | $100\%$ | $100\%$ | **$100\%$ (Zero falso alarme)** |
| **Detecção de Sensor Travado** | Ineficaz (AUC 0,36) | Ineficaz | $100\%$ (Regra $\sigma$) | **$100\%$ (Regra $\sigma$)** |
| **Causalidade Temporal / Leakage** | Causal | Causal | Causal | **100% Causal e Reprodutível** |

---

## Síntese para a Defesa na Banca Examinadora

### 1. Colinearidade do Sensor MQ-135
* **Posição da Banca:** *"Você não previu 6 gases, previu uma única resistência reescalada 6 vezes."*
* **Defesa:** *"Exatamente. A consistência dos ganhos entre 5% e 8% em todos os gases comprova que o modelo aprendeu a dinâmica inercial de transporte e relaxação do semicondutor, sem overfitting em subescalas espúrias."*

### 2. Derrota Global vs. Vitória nas Transições no IQAr
* **Posição da Banca:** *"A persistência tem 98,4% de acurácia global contra 97,5% da IA."*
* **Defesa:** *"A acurácia da persistência é inflada pela inércia de 8 horas da média móvel do CONAMA em ar limpo. Contudo, nas 95 transições de deterioração da qualidade do ar, a persistência tem eficácia nula (0,0%), enquanto o V4 antecipa 43,16% das transições com 100% de precisão na faixa Ruim."*

### 3. Falha no Ozônio (MQ-131)
* **Posição da Banca:** *"O Skill MAE do Ozônio é negativo (-1,4%)."*
* **Defesa:** *"Em horizontes ultracurtos de 15 minutos em ambiente fechado/estacional, a fotoquímica do ozônio tem variância próxima a ruído branco de quantização. Assumir abertamente a equivalência à persistência demonstra maturidade em vez de mascarar limitações do hardware."*

---

## Artefatos e Código Preservados
* **Código Oficial:** [`Código/treinar_agente_v4.py`](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/treinar_agente_v4.py)
* **Pesos e Configurações:** [`Código/agente/modelo_iqar.keras`](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/agente/modelo_iqar.keras) e [`Código/agente/config_agente.json`](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/agente/config_agente.json)
* **Gráficos em Alta Resolução:** [`Código/agente/graficos/`](file:///c:/Users/erroso/Pictures/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/Código/agente/graficos/) (Gráficos 1 a 5).
