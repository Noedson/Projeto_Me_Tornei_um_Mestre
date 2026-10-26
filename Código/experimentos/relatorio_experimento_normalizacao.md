# Relatório de Estudo de Ablação: Impacto da Normalização de Dados

**Projeto:** Agente Inteligente para Monitoramento da Qualidade do Ar em Smart Campus  
**Autor:** Noedson Romário Vieira da Silva — UFPA Tucuruí  
**Data:** 20/10/2026  
**Objetivo:** Avaliar empiricamente o comportamento dos dois agentes (**V3 e V4**) treinados **do zero** sob duas condições de entrada:
1. **Com Normalização:** Pipeline padrão (`clipping P99.5` + `log1p` + `MinMaxScaler [0, 1]`).
2. **Sem Normalização:** Dados mantidos em escala real bruta de ppm dos sensores.

---

## 1. Matriz Consolidada de Resultados

| Métrica Avaliada | V3 (Normalizado) | V3 (Sem Normalização) | V4 (Normalizado) | V4 (Sem Normalização) | Persistência Ingênua |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **CO MAE (ppm)** | 765.98 | 792.30 | **765.69** | 784.81 | 1524.38 |
| **CO RMSE (ppm)** | 57928.81 | 57930.40 | **57928.85** | 57930.74 | 81923.58 |
| **Skill Score MAE CO (%)** | +49.75% | +48.02% | **+49.77%** | +48.52% | 0,00% (Ref.) |
| **Skill Score MAE Médio (Todos Gases)** | +42.47% | +30.59% | **+42.97%** | +36.21% | 0,00% (Ref.) |
| **Acurácia nas Transições (IQAr)** | 43.16% | 55.79% | **49.47%** | 45.26% | 0,00% |
| **Acurácia Balanceada IQAr** | 97.40% | 96.67% | **97.96%** | 93.21% | 98.67% |
| **F1-Score Macro IQAr** | 97.98% | 97.30% | **98.38%** | 94.20% | 98.38% |
| **AUC Detecção Anomalias (Autoencoder)** | 94.31% | 87.41% | **93.69%** | 87.06% | N/A |
| **Épocas até Convergência** | 30 | 30 | 24 | 30 | N/A |

---

## 2. Diagnóstico Científico dos Efeitos da Normalização

### A. O que acontece com os agentes SEM normalização:
1. **Domínio de Gradientes por Escala:** As magnitudes dos gases diferem em ordens de grandeza. O erro quadrático do CO sufoca os gases de concentrações menores ($O_3$, Acetona, Tolueno).
2. **Saturação das Portas Recorrentes:** Os tensores em escala bruta (centenas de ppm) forçam as funções de ativação tanh e sigmoid para os platôs saturados, prejudicando o fluxo de retropropagação.
3. **Degradação do Autoencoder:** Sem normalização, o gargalo de 8 neurônios não consegue reconstruir simultaneamente grandezas de 0.1 ppm e 500 ppm, derrubando a AUC de detecção.

### B. V3 vs. V4 sob Normalização:
1. **V4 Oficial:** Atinge o melhor equilíbrio geral com **Skill Score positivo em todos os gases**, alta acurácia nas transições e excelente capacidade de detecção no Autoencoder.
2. **V3:** A perda assimétrica e os pesos focais no delta penalizam a calibração de amplitude mesmo com normalização.

---
*Artefatos gerados em:* `Código/experimentos/`
