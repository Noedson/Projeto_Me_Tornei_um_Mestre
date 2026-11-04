import { MongoClient } from "mongodb";
import { getDateNow } from "../helpers/getDateNow";
import { getHoursAndMinutesNow } from "../helpers/getHoursAndMinutesNow";
import { closestDateTime } from "../helpers/closestDateTime";
import { v4 as uuidv4 } from "uuid";
import { transformObject } from "../helpers/transformObject";
import dotenv from "dotenv";

dotenv.config();

const MONGO_URL = process.env.MONGO_URL || "mongodb://localhost:27017";
const DB_NAME = "mqda_local";

let clientPromise: Promise<MongoClient> | null = null;

function getMongoClient(): Promise<MongoClient> {
  if (!clientPromise) {
    const client = new MongoClient(MONGO_URL);
    clientPromise = client.connect().catch((err) => {
      clientPromise = null;
      throw err;
    });
  }
  return clientPromise;
}

export async function createDatabase(name: string) {
  try {
    const client = await getMongoClient();
    const db = client.db(DB_NAME);
    const cols = await db.listCollections({ name }).toArray();
    if (cols.length === 0) {
      await db.createCollection(name);
      console.log(`>>> [MongoDB Local] Coleção "${name}" criada em ${DB_NAME}`);
    }
  } catch (err: any) {
    console.log(`>>> [MongoDB Local] Aviso ao verificar coleção ${name}:`, err?.message);
  }
}

export async function getInformationDatabase(database: string) {
  try {
    const client = await getMongoClient();
    const db = client.db(DB_NAME);
    const count = await db.collection(database).countDocuments();
    console.log(`Informações da coleção local ${database}: ${count} documentos`);
  } catch (error) {
    console.log("Erro na função getInformationDatabase", error);
  }
}

export async function DocAlreadyExist(collectionName: string, id: string): Promise<boolean> {
  try {
    const client = await getMongoClient();
    const doc = await client.db(DB_NAME).collection<any>(collectionName).findOne({ _id: id });
    return !!doc;
  } catch {
    return false;
  }
}

export async function getRooms(): Promise<any[]> {
  try {
    const client = await getMongoClient();
    const docs = await client.db(DB_NAME).collection<any>("rooms").find({}).toArray();
    return docs.map((doc) => ({
      id: doc._id,
      name: doc.name,
      lat: doc.latitude,
      long: doc.longitude,
      campus: doc.campus,
      block: doc.block,
    }));
  } catch {
    return [];
  }
}

export async function findLastDocByIdRoom(idRoom: string): Promise<any> {
  try {
    const client = await getMongoClient();
    const docs = await client
      .db(DB_NAME)
      .collection<any>("sensors")
      .find({ roomRef: idRoom })
      .toArray();

    const storage = docs.map((doc) => ({
      _id: doc._id,
      roomRef: doc.roomRef,
      joined: doc.joined,
      LPG_MQ9_Level: doc.dataSensors?.LPG_MQ9_Level,
      CH4_MQ9_Level: doc.dataSensors?.CH4_MQ9_Level,
      CO_MQ9_Level: doc.dataSensors?.CO_MQ9_Level,
      CO_MQ135_Level: doc.dataSensors?.CO_MQ135_Level,
      Alcool_MQ135_Level: doc.dataSensors?.Alcool_MQ135_Level,
      CO2_MQ135_Level: doc.dataSensors?.CO2_MQ135_Level,
      Toluen_MQ135_Level: doc.dataSensors?.Toluen_MQ135_Level,
      MH4_MQ135_Level: doc.dataSensors?.MH4_MQ135_Level,
      Aceton_MQ135_Level: doc.dataSensors?.Aceton_MQ135_Level,
      O3_MQ131_Level: doc.dataSensors?.O3_MQ131_Level,
      Temperatura_Level: doc.dataSensors?.Temperatura_Level,
      Humidade_Level: doc.dataSensors?.Humidade_Level,
      QualityAirConcept: doc.qualityAirConcept,
      CO_MQ9_Level_IQAR: doc.sensorIQAR?.CO_MQ9_Level_IQAR,
      CO_MQ135_Level_IQAR: doc.sensorIQAR?.CO_MQ135_Level_IQAR,
      O3_MQ131_Level_IQAR: doc.sensorIQAR?.O3_MQ131_Level_IQAR,
      CalcHeatIndex: doc.calcHeatIndex,
      TargetConcept: doc.targetConcept,
    }));

    return closestDateTime(storage);
  } catch (error) {
    return error;
  }
}

export async function filterIdRooms(): Promise<any> {
  return [];
}

export async function minAndMax(): Promise<any> {
  return {};
}

export async function findAllDocsForCsv(_db: string): Promise<any> {
  return [];
}

export async function createDocumentRoom(
  collectionName: string,
  id: string,
  name: string,
  description: string,
  block: string,
  level: string,
  campus: string,
  latitude: number,
  longitude: number
) {
  const document = {
    _id: id,
    name,
    block,
    level,
    campus,
    description,
    joined: `${getDateNow()},${getHoursAndMinutesNow()}`,
    latitude,
    longitude,
  };

  try {
    const client = await getMongoClient();
    await client
      .db(DB_NAME)
      .collection<any>(collectionName)
      .updateOne({ _id: id }, { $set: document }, { upsert: true });
    return "Sala salva no MongoDB local";
  } catch (error: any) {
    return `Erro ao salvar sala no MongoDB local: ${error?.message}`;
  }
}

export async function createDocumentSensor(
  roomRef: string,
  collectionName: string,
  object: any,
  qualityAirConcept: string | undefined,
  sensorsIQAR: any,
  calcHeatIndex: any,
  targetConcept: any
) {
  const document = {
    _id: uuidv4(),
    roomRef,
    joined: `${getDateNow()},${getHoursAndMinutesNow()}`,
    dataSensors: transformObject(object),
    qualityAirConcept: qualityAirConcept,
    sensorIQAR: transformObject(sensorsIQAR),
    calcHeatIndex,
    targetConcept,
  };

  try {
    const client = await getMongoClient();
    const db = client.db(DB_NAME);
    await db.collection<any>("sensors").insertOne(document);
    if (collectionName && collectionName !== "sensors") {
      await db.collection<any>(collectionName).insertOne({ ...document });
    }
    return `Salvo no MongoDB local (${DB_NAME}.sensors | id=${document._id})`;
  } catch (error: any) {
    return `Erro ao salvar no MongoDB local: ${error?.message}`;
  }
}
