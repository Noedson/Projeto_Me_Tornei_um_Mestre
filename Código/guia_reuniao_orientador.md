# Guia Estratégico: Apresentação e Alinhamento com o Orientador
**Projeto:** Monitoramento Autônomo da Qualidade do Ar com IA Multi-Task (LoRaWAN / Django / Keras)  
**Objetivo:** Roteiro prático, fundamentação científica e respostas para perguntas difíceis em reunião de orientação e banca examinadora.

---

## 1. Roteiro de Apresentação (Pitch de 5 a 7 Minutos)

Este roteiro conta uma história científica clara: **contexto $\rightarrow$ diagnóstico das falhas da 1ª versão $\rightarrow$ soluções implementadas $\rightarrow$ resultados reais $\rightarrow$ próximos passos**.

### A. Abertura & Objetivo (1 minuto)
> *"Professor(a), o objetivo principal foi consolidar a inteligência do sistema de monitoramento da qualidade do ar (LoRaWAN/Django) integrando um **Agente Inteligente Multi-Task (Rede Recorrente LSTM)** com três tarefas simultâneas:*
> 1. *Classificação do risco de qualidade do ar (norma CONAMA 491/2018 e EPA baseadas no CO);*
> 2. *Previsão temporal (*forecasting*) de gases 15 minutos à frente;*
> 3. *Detecção autônoma de anomalias e falhas de sensores.*
> *Antes de rodar o modelo final, realizei uma auditoria rigorosa no código e nas primeiras rodadas de treino, onde identifiquei inconsistências metodológicas que inviabilizariam o trabalho numa banca. Reestruturei todo o pipeline para corrigir esses pontos."*

---

### B. Diagnóstico das Falhas Iniciais: O que você auditou e corrigiu (2 minutos)
*(Mostrar autocrítica e rigor metodológico valoriza muito a pesquisa):*

1. **Escala de tempo irrealista (5 segundos):**
   * *O problema:* A primeira versão tentava prever o ar 5 segundos à frente. Na escala de 5s, a atmosfera não varia sensivelmente; o sinal varia apenas por ruído de quantização elétrica dos sensores MQ. O modelo perdia feio para a linha de base de persistência ingênua ($x_{t+1} = x_t$).
2. **Vício de amostragem no particionamento cronológico:**
   * *O problema:* A divisão 70/15/15 tradicional alocou todos os eventos de ar deteriorado ("Ruim") no início da série. O teste ficou com 0 amostras de ar Ruim, gerando uma acurácia fictícia de 100% que mascarava a incapacidade do modelo de atuar sob risco.
3. **Descompasso com a norma ambiental (CONAMA 491/2018):**
   * *O problema:* A classificação de perigo do CO por norma exige a **média móvel de 8 horas**. Avaliar janelas pontuais instantâneas sem o histórico de 8h distorcia o enquadramento regulatório.
4. **Ponto cego do Autoencoder para Sensor Travado:**
   * *O problema:* O Autoencoder calcula erro de reconstrução. Quando um sensor trava e gera uma linha reta constante, o erro de reconstrução diminui em vez de aumentar, tornando a rede incapaz de detectar travamento por limiar de erro.

---

### C. O Novo Pipeline Científico Implementado (2 minutos)

1. **Reamostragem (*Downsampling*) para 1 minuto:** Média de 1 min com interpolação linear para falhas curtas ($\le 3$ min), eliminando ruído elétrico.
2. **Horizonte de 15 minutos:** Janela histórica de 30 minutos prevendo 15 minutos à frente — tempo hábil para tomada de decisão prática e preventiva.
3. **Particionamento em Blocos Temporais (*Blocked Time Split*):** Garantiu que eventos de ar Bom (2.758), Moderado (2.226) e Ruim (967) estivessem presentes no conjunto de teste independente.
4. **Detecção Híbrida de Falhas:** O Autoencoder é dedicado a derivas lentas (*drift*) e picos, enquanto uma regra estatística de variância temporal ($\sigma < \epsilon$) foi introduzida especificamente para sensor travado.
5. **Engenharia de Software no Django:** Agente implementado como Singleton *Thread-Safe* (`threading.Lock`), cálculo automático do histórico de 8h no banco e sistema de *cooldown* de 15 min para evitar avalanche de alertas.

---

### D. Resultados Reais e Honestidade Científica (1 a 2 minutos)

* **Previsão temporal:** Superação consistente da persistência no CO com ganho de cerca de +10% de MAE.
* **Classificação do IQAr:** $F_1$-Score Macro de **0,983**. De 967 eventos de ar crítico ("Ruim") no teste, o agente alertou **940 eventos com 15 minutos de antecedência** (Recall de 96,1% e Precisão de 100%).
* **Detecção de anomalias:** AUC acima de 0,96 para derivas e picos severos; a regra estatística de sensor travado alcançou **100% de recall** com apenas 0,22% de falso alarme.
* **Limitações mapeadas para fechamento:** 
  1. O modelo ainda erra parte das transições dinâmicas rápidas (acurácia de 29% nas mudanças de estado), decorrente da inércia da média de 8h.
  2. O limiar do autoencoder gerou ~9% de falsos alarmes em teste, o que já está mapeado para ajuste fino de especificidade.

---

## 2. Perguntas Difíceis do Orientador / Banca (Q&A de Defesa)

### P1: *"Por que usar um modelo Multi-Task e não 3 modelos separados?"*
> **Resposta:**  
> *"Três modelos separados triplicariam o custo de inferência, o consumo de memória RAM no servidor Django e o tempo de resposta do webhook. Com o Multi-Task, usamos um **Shared Encoder (Bidirectional LSTM)** que aprende uma única representação do comportamento físico dos gases, alimentando as 3 tarefas. Além de ser muito mais eficiente para deploy em edge ou servidor web, tarefas correlatas funcionam como regularizadores mútuos, diminuindo o overfitting."*

### P2: *"Como você garante que não houve vazamento de dados (data leakage) na série temporal?"*
> **Resposta:**  
> *"Tomamos três cuidados metodológicos essenciais:*  
> *1. O normalizador (`MinMaxScaler`) e os limites de clipping foram calculados **exclusivamente com a partição de treino** e apenas aplicados em validação, teste e produção.*  
> *2. A média móvel de 8 horas do CO usa janela puramente causal (olha estritamente para o passado).*  
> *3. O particionamento em blocos preservou a ordem cronológica interna de cada semana, respeitando a causalidade temporal sem misturar passado e futuro na mesma janela."*

### P3: *"Por que o Ozônio (MQ-131) não foi usado para rotular a classe do IQAr?"*
> **Resposta:**  
> *"O sensor MQ-131 utilizado é um semicondutor de baixo custo, não calibrado analiticamente em laboratório para ppb/ppm de precisão certificada (suas leituras giram em torno de 1.0, enquanto o limite normativo da OMS/CONAMA é 0,07 ppm). Classificar a saúde ambiental com base em um valor sem calibração certificada seria um erro metodológico grave. Por isso, a conformidade de norma utilizou estritamente o CO, cuja resposta e faixa de trabalho no MQ-135 são amplamente documentadas."*

### P4: *"Por que a acurácia global do IQAr é 98,4%, mas nas transições cai para 29%?"*
> **Resposta:**  
> *"Essa foi uma das análises mais ricas que fizemos: a norma do IQAr exige média móvel de 8 horas. Como uma janela de 8h tem grande inércia física, em 98% dos minutos o ar continua exatamente na mesma classe em que estava. Qualquer modelo (ou mesmo a persistência ingênua) atinge alta acurácia global simplesmente repetindo o estado anterior. Nas 93 vezes em que houve transição real de classe no teste, o modelo antecipou 29%. Nosso próximo passo de pesquisa é aplicar pesos amostrais focais (*sample weighting*) nas transições para forçar a rede a ser mais sensível a mudanças de tendência."*

### P5: *"O Autoencoder detecta se o sensor travar ou desconectar?"*
> **Resposta:**  
> *"Identificamos que o Autoencoder puro tem um ponto cego teórico para sensor travado: sinal plano constante gera erro de reconstrução baixo, fazendo com que o limiar nunca seja ultrapassado. Por isso, implementamos uma **arquitetura híbrida de detecção**: o Autoencoder cuida de picos e descalibrações (*drift*), e um módulo estatístico monitora o desvio padrão temporal recente ($\sigma < \epsilon$). Se a variância do sensor congelar, o alarme de 'sensor travado' é disparado imediatamente com 100% de recall."*

### P6: *"No Gráfico 2, por que a curva prevista parece atrasada em relação à real (o real cai antes da previsão)?"*
> **Resposta:**  
> *"Esse é um dos pontos mais interessantes da análise visual: no gráfico de validação, as curvas deveriam estar perfeitamente sobrepostas no mesmo instante do eixo X. O fato de a linha prevista reagir cerca de 15 minutos após a curva real evidencia o fenômeno clássico de **atraso de fase (*phase lag*)**. Como as quedas ou picos bruscos decorrem de fatores externos imprevistos (ex: abertura de portas), a rede adota a estratégia de menor erro médio, que é imitar a persistência defasada. Isso explica visualmente por que a acurácia em transições é de 29% e fundamenta nossa próxima melhoria: incorporar features de velocidade ($dy/dt$) e função de perda com penalidade direcional."*

---

## 3. "Colinha de Bolso" (Dados Técnicos Rápidos)

| Parâmetro | Valor Utilizado | Justificativa |
| :--- | :---: | :--- |
| **Resample / Agregação** | **1 minuto** (média) | Filtra ruído elétrico de alta frequência dos sensores MQ |
| **Janela Histórica ($X$)** | **30 minutos** (30 passos) | Contexto temporal suficiente para captar tendência |
| **Horizonte Preditivo ($y$)** | **15 minutos à frente** | Tempo hábil de resposta preventiva |
| **Amostras no Dataset** | **46.109 leituras** | Treino: 31.291 (70%) \| Val: 6.310 (15%) \| Teste: 5.951 (15%) |
| **Classes do IQAr (CO 8h)** | **Boa** ($<4,5$ ppm) \| **Mod** ($4,5 - 9,5$) \| **Ruim** ($\ge 9,5$) | Norma CONAMA 491/2018 e US-EPA AQI |
| **Arquitetura Neural** | Bi-LSTM (32) + LSTM (16) | Shared Encoder com Dropout (0.2) e 3 saídas especializadas |
| **F1-Score Macro IQAr** | **0,983** (vs 0,981 persistência) | Testado em conjunto de teste cego com 5.951 janelas |
| **Skill Score CO** | **+10,18%** de ganho de MAE | MAE Modelo 10,77 ppm vs Persistência 11,99 ppm |
| **Detecção Sensor Travado** | Recall: **100%** \| Falso Alarme: **0,22%** | Regra estatística de limiar $\sigma < \epsilon$ ($\epsilon = 0.0015$) |

---

## 4. Próximos Passos Já Mapeados (Para Mostrar Proatividade)

Se o orientador perguntar: *"E o que você vai fazer agora?"*, apresente estes 3 itens:

1. **Ajuste Fino de Falsos Alarmes:** Recalibrar o limiar do autoencoder com restrição de especificidade de 98,5% para reduzir os falsos alarmes em dados normais.
2. **Ponderação por Amostras em Transição:** Adicionar multiplicador de perda (*sample weighting*) nas janelas que antecedem transição de classe de IQAr para elevar a acurácia de transição acima de 50%.
3. **Pipeline Django em Tempo Real:** Garantir a agregação de 1 minuto em memória no serviço do Django antes de enviar para inferência, mantendo idêntico o formato do treino.
