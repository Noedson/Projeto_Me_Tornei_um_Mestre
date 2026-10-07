import numpy as numpai

class AirQualifyService:
    """
    Servicço que orquestra a inferencia do modelo Multi-Task.
    (Por enquanto, opera com logica esquelo até ser treinado)
    """

    JANELA_NECESSARIA = 12 #Leituras de Histórico (vou pesquisar depois)

    def avaliar_janela(self, sensor, leitura_queryset):
        # Passo numero 1: Garante que temos dadoss suficiente para a serie tempora
        if len(leitura_queryset) < self.JANELA_NECESSARIA:
            return None

        # Passo numero 2: Converte as leituras em uma matriz do Numpy (shape 12 passo x 7 variaveis)

        matriz = numpai.array([[
            r.co_mq135,
            r.co2_mq135,
            r.mh4_mq135,
            r.aceton_mq135,
            r.alcool_mq135,
            r.toluen_mq135,

            r.o3_mq131,
        ]for r in reversed(leitura_queryset)])

        # TODO: Quando o modelo .keras for treinado, a chamada real entrará aqui:
        # resultado = self.model.predict(matriz)

        #Regra de salvaguarda inicial para teste (Exemplo)

        ultima_leitura  = leitura_queryset[0]
        alerta = None

        #Exemplo: se o CO passar do limiar crítico imediato

        if ultima_leitura.co2_mq135 > 25.00:
            alerta = {
                "tipo": "ANOMALIA",
                "mensagem":f"Pico de CO detectadi: {ultima_leitura.co_mq135} ppm"
            }        
        
        return alerta
        