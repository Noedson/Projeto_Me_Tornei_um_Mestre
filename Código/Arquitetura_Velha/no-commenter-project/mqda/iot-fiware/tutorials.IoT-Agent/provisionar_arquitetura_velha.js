const { Client } = require("pg");
const { MongoClient } = require("mongodb");

const CODEC_JS = `function decodeUplink(input) {
  var str = "";
  for (var i = 0; i < input.bytes.length; i++) {
    str += String.fromCharCode(input.bytes[i]);
  }
  str = str.trim();
  var data = {};
  if (str.indexOf("{") === 0) {
    try {
      data = JSON.parse(str);
    } catch (e) {}
  } else {
    var parts = str.split(",");
    for (var j = 0; j < parts.length; j++) {
      var kv = parts[j].split("|");
      if (kv.length === 2 && kv[0].trim() !== "") {
        var val = parseFloat(kv[1]);
        if (!isNaN(val)) {
          data[kv[0].trim()] = val;
        }
      }
    }
  }
  return { data: data };
}
`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function provisionarChirpstack() {
  const host = process.env.CHIRPSTACK_PG_HOST || "postgres";
  const port = parseInt(process.env.CHIRPSTACK_PG_PORT || "5432", 10);
  const user = process.env.CHIRPSTACK_PG_USER || "chirpstack";
  const password = process.env.CHIRPSTACK_PG_PASSWORD || "chirpstack";
  const database = process.env.CHIRPSTACK_PG_DB || "chirpstack";
  const webhookUrl = process.env.NODERED_WEBHOOK_URL || "http://velha_nodered:1880/chirpstack";

  let client = null;
  for (let i = 0; i < 20; i++) {
    try {
      client = new Client({ host, port, user, password, database });
      await client.connect();
      const res = await client.query("SELECT id FROM tenant LIMIT 1;");
      if (res.rows.length > 0) {
        break;
      }
      await client.end();
      client = null;
    } catch (err) {
      if (client) {
        try { await client.end(); } catch (_) {}
        client = null;
      }
    }
    await sleep(2000);
  }

  if (!client) {
    console.log(">>> [CHIRPSTACK] Aviso: Banco 'chirpstack' ainda não inicializado pelo ChirpStack.");
    return;
  }

  try {
    // 1. Obtém o Tenant padrão (ChirpStack) - exatamente igual ao garantir_chirpstack.py
    const tRes = await client.query("SELECT id FROM tenant ORDER BY created_at ASC LIMIT 1;");
    const tenantId = tRes.rows[0].id;

    // 2. Garante o Gateway (a84041ffff2385aa - mesmo ID do event_up.csv e do LWN-Simulator)
    const gwIdHex = "a84041ffff2385aa";
    await client.query(
      `INSERT INTO gateway (
        gateway_id, tenant_id, created_at, updated_at,
        name, description, latitude, longitude, altitude,
        stats_interval_secs, tags, properties, downlink_priority
      ) VALUES (
        decode($1, 'hex'), $2, NOW(), NOW(),
        'Gateway_Campus_Sim', 'Gateway LoRaWAN AU915_0 (Simulador / Campus)',
        -5.33451, -49.08876, 124.0,
        30, '{}'::jsonb, '{}'::jsonb, 0
      )
      ON CONFLICT (gateway_id) DO NOTHING;`,
      [gwIdHex, tenantId]
    );

    // 3. Garante o Device Profile (Central_Sensores1 com Codec JS) - exatamente igual ao garantir_chirpstack.py
    const dpId = "9dda9ee1-e69b-4880-9be0-23d4b3e80fd1";
    const appLayerParams = JSON.stringify({
      ts003_version: null,
      ts004_version: null,
      ts005_version: null,
      ts003_f_port: 202,
      ts004_f_port: 201,
      ts005_f_port: 200,
    });
    await client.query(
      `INSERT INTO device_profile (
        id, tenant_id, created_at, updated_at,
        name, description, region, mac_version, reg_params_revision,
        adr_algorithm_id, payload_codec_runtime, payload_codec_script,
        uplink_interval, device_status_req_interval,
        supports_otaa, supports_class_b, supports_class_c,
        tags, flush_queue_on_activate, measurements, auto_detect_measurements,
        region_config_id, allow_roaming, rx1_delay,
        app_layer_params, firmware_version, vendor_profile_id, supported_uplink_data_rates
      ) VALUES (
        $1, $2, NOW(), NOW(),
        'Central_Sensores1', 'Perfil de Sensores de Qualidade do Ar (MQ135 + MQ131)',
        'AU915', '1.0.3', 'A',
        'default', 'JS', $3,
        30, 1,
        TRUE, FALSE, FALSE,
        '{}'::jsonb, TRUE, '{}'::jsonb, TRUE,
        'au915_0', FALSE, 0,
        $4::jsonb, '1.0.0', 0, '{0,1,2,3,4,5}'
      )
      ON CONFLICT (id) DO UPDATE SET
        payload_codec_runtime = 'JS',
        payload_codec_script = EXCLUDED.payload_codec_script,
        region = 'AU915',
        region_config_id = 'au915_0';`,
      [dpId, tenantId, CODEC_JS, appLayerParams]
    );

    // 4. Garante a Application (IQAr_Campus) - exatamente igual ao garantir_chirpstack.py
    const appId = "ead6f393-bb6f-42ea-90f7-5c870a658e89";
    await client.query(
      `INSERT INTO application (
        id, tenant_id, created_at, updated_at,
        name, description, tags
      ) VALUES (
        $1, $2, NOW(), NOW(),
        'IQAr_Campus', 'Monitoramento de Qualidade do Ar - Smart Campus',
        '{}'::jsonb
      )
      ON CONFLICT (id) DO NOTHING;`,
      [appId, tenantId]
    );

    // 5. Garante a Integração HTTP apontando para o Webhook do Node-RED (http://velha_nodered:1880/chirpstack)
    const httpConfig = JSON.stringify({
      Http: {
        headers: {},
        json: true,
        event_endpoint_url: webhookUrl,
      },
    });
    await client.query(
      `INSERT INTO application_integration (
        application_id, kind, created_at, updated_at, configuration
      ) VALUES (
        $1, 'Http', NOW(), NOW(), $2::jsonb
      )
      ON CONFLICT (application_id, kind) DO UPDATE SET
        configuration = EXCLUDED.configuration,
        updated_at = NOW();`,
      [appId, httpConfig]
    );

    // 6. Garante o Dispositivo (Sensor_Galpao_lab - d3afdcdc546af01d) - exatamente igual ao garantir_chirpstack.py
    const devEuiHex = "d3afdcdc546af01d";
    const joinEuiHex = "0000000000000000";
    await client.query(
      `INSERT INTO device (
        dev_eui, application_id, device_profile_id,
        created_at, updated_at,
        name, description, external_power_source,
        enabled_class, skip_fcnt_check, is_disabled,
        tags, variables, join_eui, app_layer_params, f_cnt_up
      ) VALUES (
        decode($1, 'hex'), $2, $3,
        NOW(), NOW(),
        'Sensor_Galpao_lab', 'Nó Sensor LoRaWAN (MQ-135 e MQ-131)', FALSE,
        'A', TRUE, FALSE,
        '{}'::jsonb, '{}'::jsonb, decode($4, 'hex'), '{}'::jsonb, 0
      )
      ON CONFLICT (dev_eui) DO UPDATE SET
        application_id = EXCLUDED.application_id,
        device_profile_id = EXCLUDED.device_profile_id,
        skip_fcnt_check = TRUE,
        is_disabled = FALSE,
        updated_at = NOW();`,
      [devEuiHex, appId, dpId, joinEuiHex]
    );

    // 7. Garante a chave OTAA (AppKey / NwkKey = 000102030405060708090a0b0c0d0e0f)
    const keyHex = "000102030405060708090a0b0c0d0e0f";
    await client.query(
      `INSERT INTO device_keys (
        dev_eui, created_at, updated_at,
        nwk_key, app_key, dev_nonces, join_nonce, gen_app_key
      ) VALUES (
        decode($1, 'hex'), NOW(), NOW(),
        decode($2, 'hex'), decode($2, 'hex'),
        '{}'::jsonb, 0, decode('00000000000000000000000000000000', 'hex')
      )
      ON CONFLICT (dev_eui) DO UPDATE SET
        nwk_key = EXCLUDED.nwk_key,
        app_key = EXCLUDED.app_key,
        dev_nonces = '{}'::jsonb,
        updated_at = NOW();`,
      [devEuiHex, keyHex]
    );

    console.log("[CHIRPSTACK] Provisionamento automático verificado com sucesso (Gateway, Perfil Central_Sensores1, Codec JS, App IQAr_Campus, Webhook HTTP -> Node-RED e Sensor_Galpao_lab)!");
  } catch (err) {
    console.error("[CHIRPSTACK] Erro ao verificar provisionamento:", err.message);
  } finally {
    await client.end();
  }
}

async function provisionarMongoEFiware() {
  const mongoUrl = process.env.MONGO_URL || "mongodb://mongo-db:27017";
  const proxyUrl = `http://127.0.0.1:${process.env.PORT || 4000}`;

  // 1. Cria índices no MongoDB para Orion e IoT-Agent
  for (let i = 0; i < 20; i++) {
    let mClient = null;
    try {
      mClient = new MongoClient(mongoUrl);
      await mClient.connect();

      for (const dbName of ["orion", "orion-openiot"]) {
        const db = mClient.db(dbName);
        const col = db.collection("entities");
        await col.createIndex({ "_id.servicePath": 1, "_id.id": 1, "_id.type": 1 }, { unique: true });
        await col.createIndex({ "_id.type": 1 });
        await col.createIndex({ "_id.id": 1 });
      }

      const iotaDb = mClient.db("iotagentul");
      const devCol = iotaDb.collection("devices");
      await devCol.createIndex({ "_id.service": 1, "_id.id": 1, "_id.type": 1 });
      await devCol.createIndex({ "_id.type": 1 });
      await devCol.createIndex({ "_id.id": 1 });
      const grpCol = iotaDb.collection("groups");
      await grpCol.createIndex({ "_id.resource": 1, "_id.apikey": 1, "_id.service": 1 });
      await grpCol.createIndex({ "_id.type": 1 });

      await mClient.close();
      console.log(">>> [MongoDB] Índices do Orion e IoT-Agent verificados com sucesso!");
      break;
    } catch (err) {
      if (mClient) {
        try { await mClient.close(); } catch (_) {}
      }
      await sleep(2000);
    }
  }

  // 2. Aguarda Proxy (4000), Orion (1026) e IoT-Agent (4041) estarem prontos
  const orionUrl = process.env.ORION_URL || "http://orion:1026";
  const iotaNorthUrl = process.env.IOTA_NORTH_URL || "http://iot-agent:4041";

  for (let i = 0; i < 30; i++) {
    try {
      const rProxy = await fetch(`${proxyUrl}/ping`);
      const rOrion = await fetch(`${orionUrl}/version`);
      const rIota = await fetch(`${iotaNorthUrl}/iot/about`);
      if (rProxy.ok && rOrion.ok && rIota.ok) break;
    } catch (_) {}
    await sleep(2000);
  }

  try {
    // 2.1 Cria a sala room:001 no Orion
    await fetch(`${proxyUrl}/create-room`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: "room:001",
        name: "Galpão Laboratório",
        description: "Sala monitorada pelos sensores MQ-135 e MQ-131",
        block: "Bloco A",
        level: "Térreo",
        campus: "Campus III",
        latitude: -5.33451,
        longitude: -49.08876,
      }),
    });

    // 2.2 Cria o Service Group no IoT-Agent (apikey 4jggokgpepnvsb2uv4s40d59ov)
    await fetch(`${proxyUrl}/create-service-iot`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity_type: "Sensor" }),
    });

    // 2.3 Provisiona todos os sensores de gases e clima para sensor_001-room:001
    const gases = [
      "CO_MQ135",
      "CO2_MQ135",
      "Alcool_MQ135",
      "Aceton_MQ135",
      "Toluen_MQ135",
      "MH4_MQ135",
      "O3_MQ131",
      "CO_MQ7",
      "LPG_MQ9",
      "CH4_MQ9",
      "CO_MQ9",
      "Temperatura",
      "Humidade",
    ];

    for (const gas of gases) {
      await fetch(`${proxyUrl}/create-sensors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          device_id: `${gas}_001`,
          entity_name: `${gas}:001`,
          entity_type: "Sensor",
          object_id: `${gas}_Level`,
          nameAtribute: `${gas}_Level`,
          typeAtribute: "Number",
          foreignkeyNameRef: "refRoom",
          foreignkeyValueRef: "room:001",
        }),
      });
    }

    // 2.4 Cria a Subscription no Orion para notificar o Cygnus (Orion -> Cygnus -> MongoDB)
    const subRes = await fetch(`${orionUrl}/v2/subscriptions`, {
      method: "GET",
      headers: {
        "fiware-service": "openiot",
        "fiware-servicepath": "/",
      },
    });
    const subs = subRes.ok ? await subRes.json() : [];
    if (!Array.isArray(subs) || subs.length === 0) {
      await fetch(`${orionUrl}/v2/subscriptions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "fiware-service": "openiot",
          "fiware-servicepath": "/",
        },
        body: JSON.stringify({
          description: "Notificar Cygnus de todas as mudanças nos Sensores para histórico no MongoDB",
          subject: {
            entities: [{ idPattern: ".*", type: "Sensor" }],
          },
          notification: {
            http: { url: "http://cygnus:5051/notify" },
            attrsFormat: "legacy",
          },
        }),
      });
    }

    console.log(">>> [FIWARE Proxy] Sala 'room:001', Service Group, Sensores (*_001) e Subscription Orion -> Cygnus -> MongoDB provisionados!");
  } catch (err) {
    console.error(">>> [FIWARE Proxy] Erro ao provisionar entidades FIWARE:", err.message);
  }
}

async function main() {
  await sleep(2000);
  await Promise.all([provisionarChirpstack(), provisionarMongoEFiware()]);
}

main();
