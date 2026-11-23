abstract class Usuario {
    private int id;
    private String nome;
    private String email;
    private String matricula;
    private boolean ativo;
}

class GestorAmbiental extends Usuario {
    private String setorMonitorado;
    private boolean receberNotificacaoCritica;
}

class AdministradorSistema extends Usuario {
    private String nivelAcesso;
    private String chaveAutorizacaoMLOps;
}

class NoSensor {
    private String devEui;
    private String nome;
    private String localizacao;
    private boolean ativo;
    private String criadoEm;
}

class LeituraAmbiental {
    private int id;
    private String timestamp;
    private float coMq135;
    private float co2Mq135;
    private float nh4Mq135;
    private float acetonaMq135;
    private float alcoolMq135;
    private float toluenoMq135;
    private float o3Mq131;
    private float mediaMovelCo8h;
}

class ModeloNeural {
    private String versao;
    private String caminhoArquivoKeras;
    private String caminhoScalerPkl;
    private float acuraciaValidacao;
    private String dataCarregamento;
    private boolean emExecucao;
}

class AlertaAgente {
    private int id;
    private String timestamp;
    private String tipo;
    private String severidade;
    private String mensagem;
    private boolean resolvido;
    private String dataResolucao;
}
