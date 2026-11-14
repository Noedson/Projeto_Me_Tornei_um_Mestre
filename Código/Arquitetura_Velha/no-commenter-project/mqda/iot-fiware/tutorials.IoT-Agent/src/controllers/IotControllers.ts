import express, { Request, Response } from "express";
import fs from "fs";
import http from "http";
import path from "path";
import { performance } from "perf_hooks";
import { serviceIot } from "../services/CreateServiceIot";
import { sendDataAgent } from "../services/SendDataDevice";
import { getAllSensors } from "../services/ShowSensors";
import { createRoom } from "../models/RoomLiving";
import { createSensor } from "../models/Sensor";
import { getAllRooms } from "../services/ShowRooms";
import { createDocumentRoom, createDocumentSensor, getRooms, findLastDocByIdRoom } from "../db/Cloudant";
import { format } from "../helpers/formatDataSensors";
import { calcIQAR } from "../helpers/calcIQAR";
import { calculateHeatIndex, targetConcept } from "../helpers/calcHeatIndex";

const MONITORAMENTO_DIR = "/app/monitoramento";
const ESTADO_AGENTE_PATH = path.join(MONITORAMENTO_DIR, "estado_agente.json");

function obterEstadoAgente(): boolean {
  try {
    if (fs.existsSync(ESTADO_AGENTE_PATH)) {
      const raw = fs.readFileSync(ESTADO_AGENTE_PATH, "utf-8");
      const parsed = JSON.parse(raw);
      return String(parsed.usar_agente) === "1" || parsed.usar_agente === true;
    }
  } catch (_) {}
  return process.env.USAR_AGENTE === "1";
}

function registrarMetricaLeitura(payload: Record<string, any>) {
  try {
    const corpo = JSON.stringify(payload);
    const req = http.request(
      {
        hostname: "monitor-recursos",
        port: 9096,
        path: "/api/leitura",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(corpo),
        },
        timeout: 1500,
      },
      (res) => res.resume()
    );
    req.on("error", () => {});
    req.write(corpo);
    req.end();
  } catch (_) {}
}

export const ping = async (req: Request, res: Response) => {
  res.status(200).json({ pong: "ok" });
};

export const CREATE_ROOMS = async (req: Request, res: Response) => {
  let { id, name, description, block, level, campus, latitude, longitude } = req.body;
  if (id && name && description && block && level && campus) {
    const create = await createRoom(id, name, description, block, level, campus, latitude, longitude)
      .then((response) => response)
      .catch((error) => error);
    const mongoLocal = await createDocumentRoom(
      "rooms",
      id,
      name,
      description,
      block,
      level,
      campus,
      latitude,
      longitude
    )
      .then((response) => response)
      .catch((error) => error);
    res.status(200).json({ ok: create, mongodb: mongoLocal });
  } else {
    res.json({ error: "Informe os dados corretamente" });
  }
};

export const SHOW_ROOMS = async (req: Request, res: Response) => {
  let { entity_name } = req.params;
  const ShowRooms = await getAllRooms(entity_name)
    .then((response) => response)
    .catch((error) => error);
  res.status(200).json({ rooms: ShowRooms });
};

export const SHOW_ALL_ROOMS = async (req: Request, res: Response) => {
  const ShowRooms = await getRooms()
    .then((response) => response)
    .catch((error) => error);
  res.status(200).json({ rooms: ShowRooms });
};

export const SHOW_LAST_DOC_BY_ID_ROOM = async (req: Request, res: Response) => {
  let { idRoom } = req.params;
  if (idRoom) {
    const allDocs = await findLastDocByIdRoom(idRoom)
      .then((response) => response)
      .catch((error) => error);
    res.status(200).json({ docs: allDocs });
  }
};

export const CREATE_SERVICE_IOT = async (req: Request, res: Response) => {
  let { entity_type } = req.body;
  const service = await serviceIot(entity_type)
    .then((response) => response)
    .catch((error) => error);
  res.status(200).json({ ok: service });
};

export const CREATE_SENSORS = async (req: Request, res: Response) => {
  let {
    device_id,
    entity_name,
    entity_type,
    object_id,
    nameAtribute,
    typeAtribute,
    foreignkeyNameRef,
    foreignkeyValueRef,
  } = req.body;

  const sensor = await createSensor(
    device_id,
    entity_name,
    entity_type,
    object_id,
    nameAtribute,
    typeAtribute,
    foreignkeyNameRef,
    foreignkeyValueRef
  )
    .then((response) => response)
    .catch((error) => error);

  res.status(200).json({ ok: sensor });
};

export const SUBMIT_DATA_AGENT = async (req: Request, res: Response) => {
  const tInicioTotal = performance.now();
  let { room, data, time } = req.body;
  let sensorDataObject: { [key: string]: number } = {};
  let arr: any = [];

  if (room && data) {
    const formattedData = format(data, room);
    if (formattedData instanceof Error) {
      return res.status(400).json({ error: formattedData.message });
    }

    await Promise.all(
      formattedData.map(async (current: any) => {
        const sensorName = current[1].split("|")[0];
        const sensorValue = parseFloat(current[1].split("|")[1]);
        sensorDataObject[sensorName] = sensorValue;
        await sendDataAgent(current[0], current[1]);
        console.log(sensorName + "," + sensorValue);
        arr.push({ sensorName, sensorValue });
      })
    );

    const temp_rh: any = arr.filter(
      (substance: any) =>
        substance.sensorName === "Temperatura_Level" || substance.sensorName === "Humidade_Level"
    );
    temp_rh.sort((a: any, b: any) => {
      if (a.sensorName === "Temperatura_Level") return -1;
      if (b.sensorName === "Temperatura_Level") return 1;
      return 0;
    });

    const temperatura = temp_rh[0]?.sensorValue ?? 27;
    const umidade = temp_rh[1]?.sensorValue ?? 60;
    const heatIndex = calculateHeatIndex(temperatura, umidade);
    const heatConcept = targetConcept(temperatura, umidade);
    const [iqarLabel, iqarDados] = calcIQAR(arr);

    const coAtual = sensorDataObject["CO_MQ135_Level"] ?? 0.0;
    const iqarReativo = coAtual >= 9.5 ? "Ruim" : coAtual >= 4.5 ? "Moderada" : "Boa";
    const alertaReativo = iqarReativo === "Ruim" || (iqarLabel && iqarLabel !== "Boa" && iqarLabel !== "Moderada");

    console.log(`Qualidade do Ar (Tabela calcIQAR): ${iqarLabel} | CO=${coAtual.toFixed(2)} ppm (IQAr EPA=${iqarReativo})`);
    console.log("Dados IQAR:", iqarDados);
    if (alertaReativo) {
      console.log(`>>> [AVISO REATIVO - POLUICAO PRESENTE] CO atual (${coAtual.toFixed(2)} ppm) atingiu nivel critico (${iqarLabel})!`);
    }

    const mongoLocal = await createDocumentSensor(
      room,
      "galpaotocorredordois",
      sensorDataObject as any,
      iqarLabel,
      iqarDados as any,
      heatIndex as any,
      heatConcept as any
    );

    const usarAgente = obterEstadoAgente();
    let iqarPrevisto15m = "";
    let coPrevisto15m = "";
    let anomaliaDetectada: string | number = "";
    let erroReconstrucao = "";
    let tipoAlertaAgente = "";
    let latenciaAgenteMs = 0.0;

    if (usarAgente) {
      const agenteUrl = process.env.AGENTE_IA_URL || "http://velha_agente_ia:5000/avaliar";
      const tInicioAgente = performance.now();
      try {
        const respAgente = await fetch(agenteUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            room,
            timestamp: time || new Date().toISOString(),
            gases: {
              CO_MQ135: sensorDataObject["CO_MQ135_Level"] ?? 0.0,
              CO2_MQ135: sensorDataObject["CO2_MQ135_Level"] ?? 0.0,
              MH4_MQ135: sensorDataObject["MH4_MQ135_Level"] ?? 0.0,
              Aceton_MQ135: sensorDataObject["Aceton_MQ135_Level"] ?? 0.0,
              Alcool_MQ135: sensorDataObject["Alcool_MQ135_Level"] ?? 0.0,
              Toluen_MQ135: sensorDataObject["Toluen_MQ135_Level"] ?? 0.0,
              O3_MQ131: sensorDataObject["O3_MQ131_Level"] ?? 0.0,
            },
          }),
        });
        latenciaAgenteMs = performance.now() - tInicioAgente;
        if (respAgente.ok) {
          const resultado: any = await respAgente.json();
          if (resultado.pronto) {
            iqarPrevisto15m = resultado.classe || "";
            const prevCoVal = resultado.previsao?.CO_MQ135 ?? 0.0;
            coPrevisto15m = Number(prevCoVal).toFixed(4);
            anomaliaDetectada = resultado.anomalia ? 1 : 0;
            erroReconstrucao = Number(resultado.erro_reconstrucao ?? 0).toFixed(6);
            console.log(
              `>>> [Agente IA - Arq. Velha] IQAr Previsto (15m): ${iqarPrevisto15m} | ` +
              `CO Previsto=${Number(prevCoVal).toFixed(2)} ppm | Erro Rec=${Number(resultado.erro_reconstrucao).toFixed(4)} | ` +
              `Anomalia=${resultado.anomalia} | Tempo Agente=${latenciaAgenteMs.toFixed(2)} ms`
            );
            if (resultado.alerta) {
              tipoAlertaAgente = resultado.alerta.tipo || "";
              console.log(`>>> [ALERTA AGENTE IA - ARQ. VELHA] [${resultado.alerta.tipo}] ${resultado.alerta.mensagem}`);
            }
          } else {
            console.log(`>>> [Agente IA - Arq. Velha] Coletando janela inicial (${resultado.amostras_atuais || 0}/${resultado.amostras_necessarias || 32})...`);
          }
        }
      } catch (errAgente: any) {
        latenciaAgenteMs = performance.now() - tInicioAgente;
        console.log(`>>> [Aviso Agente IA - Arq. Velha] Erro ao consultar servico do agente: ${errAgente?.message}`);
      }
    } else {
      console.log(">>> [Modo SEM AGENTE] Inferencia IA desativada (USAR_AGENTE=0). Apenas monitoramento reativo calcIQAR.");
    }

    const latenciaTotalMs = performance.now() - tInicioTotal;
    registrarMetricaLeitura({
      timestamp_recebimento: new Date().toISOString(),
      timestamp_sensor: time || new Date().toISOString(),
      arquitetura: "Arquitetura_Velha",
      usar_agente: usarAgente ? 1 : 0,
      dev_eui: room,
      co_atual: coAtual.toFixed(4),
      iqar_reativo_presente: iqarReativo,
      alerta_reativo_presente: alertaReativo ? 1 : 0,
      iqar_previsto_15m: iqarPrevisto15m,
      co_previsto_15m: coPrevisto15m,
      anomalia_detectada: anomaliaDetectada,
      erro_reconstrucao: erroReconstrucao,
      tipo_alerta_agente: tipoAlertaAgente,
      latencia_total_ms: latenciaTotalMs.toFixed(3),
      latencia_agente_ms: latenciaAgenteMs.toFixed(3),
    });

    res.status(200).json({
      ok: "---Dados Recebidos ---",
      data,
      iqar: iqarLabel,
      usar_agente: usarAgente,
      iqar_previsto_15m: iqarPrevisto15m || null,
      latencia_total_ms: Number(latenciaTotalMs.toFixed(3)),
      latencia_agente_ms: Number(latenciaAgenteMs.toFixed(3)),
      mongodb: mongoLocal,
    });
  } else {
    res.status(400).json({ error: "Informe os dados corretamente" });
  }
};

export const SHOW_SENSORS = async (req: Request, res: Response) => {
  let { entity_name } = req.params;
  const showSensors = await getAllSensors(entity_name)
    .then((response) => response)
    .catch((error) => error);
  res.status(200).json({ devices: showSensors });
};
