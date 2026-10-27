# Registro Completo da Sessão: Avaliação Crítica, Análise do Gráfico 2 e Próximos Passos

**Projeto:** Monitoramento Autônomo da Qualidade do Ar com IA Multi-Task (LoRaWAN / Django / Keras)  
**Data da Sessão:** 14/10/2026  
**Status:** Conversa e diagnósticos consolidados para implementação futura.

---

## 1. Síntese da Avaliação Crítica e Sincera dos Dados Atuais

Foi realizada uma auditoria cruzada entre as métricas reais (`agente/metricas_finais.json`), o histórico de épocas (`agente/historico_treinamento.csv`) e o pipeline de código:

### A. Pontos Fortes Consolidados
* **Metodologia de Particionamento:** A transição para *Blocked Time-Series Split* corrigiu o vício da 1ª versão, garantindo classes Bom (2.758), Moderado (2.226) e Ruim (967) no conjunto de teste independente.
* **Detecção de Sensor Travado:** A regra estatística de variância temporal ($\sigma < \epsilon$) supriu com sucesso a deficiência teórica do autoencoder para sinais estáticos, atingindo **100% de recall** com **0,22% de falsos alarmes**.
* **Previsão de Risco Crítico:** O classificador antecipou **940 de 967 ocorrências** de ar "Ruim" no teste (Recall de 96,1% e Precisão de 100%).

### B. Vulnerabilidades Críticas Identificadas
1. **Acurácia Ilusória no IQAr (A armadilha das transições):**
   * A acurácia global é de **98,40%**, mas a linha de base ingênua de persistência também atinge **98,44%**.
   * Nas 93 mudanças reais de classe no teste, a acurácia é de apenas **29,03% (70,97% de erro)**, reflexo da inércia da média móvel de 8 horas.
2. **Previsão com RMSE Elevado no CO e Ozônio Negativo:**
   * O ganho no CO existe (+10,18% de MAE), mas o **RMSE é de 169,97 ppm**, apontando para outliers pontuais graves.
   * O Ozônio (MQ-131) apresentou **Skill Score negativo (-1,70%)**, sendo superado pela persistência.
3. **Taxa de Falso Alarme do Autoencoder (9,12%):**
   * Em dados perfeitamente normais de teste, o limiar gerou ~9% de disparos falsos (~130 alarmes espúrios/dia).
4. **Descompasso Temporal no Django (*Training-Serving Skew*):**
   * O modelo foi treinado com médias reamostradas de 1 minuto, enquanto a view do Django atualmente repassa leituras cruas pontuais.

---

## 2. Análise Detalhada do Gráfico 2 (Atraso de Fase / *Phase Lag*)

### Pergunta-Chave: *"O Real deve vir antes da Previsão?"*
* **No mundo real (Operação/Alarme):** SIM. O alerta é emitido 15 minutos antes do evento acontecer fisicamente.
* **No gráfico de validação científica:** **NÃO.** No gráfico, as curvas Real e Previsto deveriam estar **perfeitamente sobrepostas no mesmo ponto do eixo X**.

### O que o Gráfico 2 revelou visualmente:
* **No CO (minutos 50 a 100):** O sensor real (linha preta) despenca no minuto 50. A previsão do LSTM (linha azul) só começa a cair no minuto 65 (15 minutos depois). A linha azul segue quase que perfeitamente a linha cinza (persistência defasada).
* **No Ozônio (minutos 200 a 220):** O pico real ocorre no minuto 200. O pico desenhado pela rede só surge no minuto 215.

### Por que a rede faz isso?
A rede tenta minimizar o erro matemático global (Huber Loss). Como em 95% do tempo a concentração de gás varia pouco, a resposta matematicamente mais "segura" encontrada pelo otimizador é prever variação próxima de zero ($\Delta \approx 0 \implies \hat{y}_{t+15} \approx x_t$).  
Com isso, a rede passa a atuar como um **espelho com atraso de 15 minutos**, reagindo às quedas e subidas somente depois que elas já entraram na janela observada. Essa é a explicação exata para a acurácia de 29% nas transições.

---

## 3. Roteiro de Modificações Futuras (Plano de Ação)

Quando você for executar a atualização do código, estas são as 4 etapas planejadas:

### Etapa 1: Injeção de Features de Velocidade e Aceleração
Adicionar ao pré-processamento o cálculo de tendência instantânea e de curto prazo:
* $\Delta_1 = x_t - x_{t-1}$ (velocidade de variação em 1 min)
* $\Delta_5 = x_t - x_{t-5}$ (tendência dos últimos 5 min)
* Derivada da média móvel de 8h ($\Delta \text{Média}_{30\text{min}}$)  
*Objetivo:* Dar à rede informação explícita de inclinação da curva para antecipar o movimento futuro.

### Etapa 2: Função de Perda com Penalidade Direcional (*Directional Loss*)
Substituir o Huber Loss simples da saída de delta por uma perda com penalidade de sinal oposto:
```python
@tf.keras.utils.register_keras_serializable(package="agente")
def perda_delta_direcional(y_true, y_pred):
    huber = tf.keras.losses.Huber()(y_true, y_pred)
    # Penaliza severamente quando a direção prevista é contrária à real
    sinal_oposto = tf.cast((y_true * y_pred) < 0, tf.float32)
    penalidade = tf.reduce_mean(sinal_oposto * tf.abs(y_true - y_pred))
    return huber + 0.5 * penalidade
```
*Objetivo:* Forçar a rede a se comprometer com a direção da subida ou descida, punindo a inércia de prever delta nulo.

### Etapa 3: Ponderação de Amostras em Transição (*Sample Weighting*)
Aplicar pesos maiores no cálculo da perda para janenas em que a classe futura difere da classe atual:
```python
# Amostras onde ocorre mudança de faixa ganham peso 3x maior no treino
peso_amostra = np.where(ycls_train != ycls_atual, 3.0, 1.0)
```
*Objetivo:* Elevar a acurácia de transição de classe de 29% para patamares superiores a 50%.

### Etapa 4: Recalibração de Especificidade do Limiar de Anomalia
Ajustar o limiar para garantir especificidade de 98,5% sob dados normais de validação, reduzindo a taxa de falso alarme em teste de 9,12% para menos de 2%.

### Etapa 5: Harmonização da Ingestão no Django
No `AirQualifyService` ([agente/services.py](file:///e:/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/C%C3%B3digo/agente/services.py)), aplicar agregação por média em 1 minuto nas últimas 40 leituras antes da inferência, eliminando o *training-serving skew*.

---

## 4. Destaques para a Reunião com o Orientador

Lembre-se de levar os seguintes pontos-chave estruturados no documento [guia_reuniao_orientador.md](file:///e:/Projeto_Me_Tornei_Um_Mestre/Projeto_Me_Tornei_um_Mestre/C%C3%B3digo/guia_reuniao_orientador.md):
1. **Apresentar o Gráfico 2 com postura proativa:** Mostrar o fenômeno de atraso de fase (*lag*) como um achado científico consciente, explicando a inércia da persistência e apresentando a proposta das derivadas e da perda direcional como solução.
2. **Defender a arquitetura Multi-Task:** Ressaltar economia de memória, inferência única e menor sobreajuste via representação compartilhada (Bi-LSTM).
3. **Explicar a regra estatística de sensor travado:** Demonstrar maturidade ao admitir a limitação teórica do autoencoder para sinais planos e valorizar a heurística híbrida com 100% de recall.
