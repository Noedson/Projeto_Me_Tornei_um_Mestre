import os
import json
import time
import psycopg2

CODEC_JS = """function decodeUplink(input) {
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
"""

def garantir_provisionamento_chirpstack():
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "postgres_password")

    # Aguarda o ChirpStack aplicar suas migrações na base 'chirpstack'
    conn = None
    for tentativa in range(15):
        try:
            conn = psycopg2.connect(
                dbname="chirpstack",
                user=user,
                password=password,
                host=host,
                port=port,
            )
            cur = conn.cursor()
            cur.execute("SELECT id FROM tenant LIMIT 1;")
            row = cur.fetchone()
            if row:
                break
            cur.close()
            conn.close()
            conn = None
        except Exception:
            if conn:
                conn.close()
                conn = None
        time.sleep(2)

    if not conn:
        print("[CHIRPSTACK] Aviso: Banco 'chirpstack' ainda não inicializado pelo ChirpStack. Pulando provisionamento automático.")
        return

    try:
        with conn:
            with conn.cursor() as cur:
                # 1. Obtém o Tenant padrão (ChirpStack)
                cur.execute("SELECT id FROM tenant ORDER BY created_at ASC LIMIT 1;")
                tenant_id = cur.fetchone()[0]

                # 2. Garante o Gateway (a84041ffff2385aa - mesmo ID do event_up.csv e do LWN-Simulator)
                gw_id_hex = "a84041ffff2385aa"
                cur.execute(
                    """
                    INSERT INTO gateway (
                        gateway_id, tenant_id, created_at, updated_at,
                        name, description, latitude, longitude, altitude,
                        stats_interval_secs, tags, properties, downlink_priority
                    )
                    VALUES (
                        decode(%s, 'hex'), %s, NOW(), NOW(),
                        'Gateway_Campus_Sim', 'Gateway LoRaWAN AU915_0 (Simulador / Campus)',
                        -5.33451, -49.08876, 124.0,
                        30, '{}'::jsonb, '{}'::jsonb, 0
                    )
                    ON CONFLICT (gateway_id) DO NOTHING;
                    """,
                    (gw_id_hex, tenant_id),
                )

                # 3. Garante o Device Profile (Central_Sensores1 com Codec JS)
                dp_id = "9dda9ee1-e69b-4880-9be0-23d4b3e80fd1"
                app_layer_params = json.dumps({
                    "ts003_version": None,
                    "ts004_version": None,
                    "ts005_version": None,
                    "ts003_f_port": 202,
                    "ts004_f_port": 201,
                    "ts005_f_port": 200,
                })
                cur.execute(
                    """
                    INSERT INTO device_profile (
                        id, tenant_id, created_at, updated_at,
                        name, description, region, mac_version, reg_params_revision,
                        adr_algorithm_id, payload_codec_runtime, payload_codec_script,
                        uplink_interval, device_status_req_interval,
                        supports_otaa, supports_class_b, supports_class_c,
                        tags, flush_queue_on_activate, measurements, auto_detect_measurements,
                        region_config_id, allow_roaming, rx1_delay,
                        app_layer_params, firmware_version, vendor_profile_id, supported_uplink_data_rates
                    )
                    VALUES (
                        %s, %s, NOW(), NOW(),
                        'Central_Sensores1', 'Perfil de Sensores de Qualidade do Ar (MQ135 + MQ131)',
                        'AU915', '1.0.3', 'A',
                        'default', 'JS', %s,
                        30, 1,
                        TRUE, FALSE, FALSE,
                        '{}'::jsonb, TRUE, '{}'::jsonb, TRUE,
                        'au915_0', FALSE, 0,
                        %s::jsonb, '1.0.0', 0, '{0,1,2,3,4,5}'
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        payload_codec_runtime = 'JS',
                        payload_codec_script = EXCLUDED.payload_codec_script,
                        region = 'AU915',
                        region_config_id = 'au915_0';
                    """,
                    (dp_id, tenant_id, CODEC_JS, app_layer_params),
                )

                # 4. Garante a Application (IQAr_Campus)
                app_id = "ead6f393-bb6f-42ea-90f7-5c870a658e89"
                cur.execute(
                    """
                    INSERT INTO application (
                        id, tenant_id, created_at, updated_at,
                        name, description, tags
                    )
                    VALUES (
                        %s, %s, NOW(), NOW(),
                        'IQAr_Campus', 'Monitoramento de Qualidade do Ar - Smart Campus',
                        '{}'::jsonb
                    )
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    (app_id, tenant_id),
                )

                # 5. Garante a Integração HTTP apontando para o Webhook do Django
                http_config = json.dumps({
                    "Http": {
                        "headers": {},
                        "json": True,
                        "event_endpoint_url": "http://web:8000/api/chirpstack/webhook/",
                    }
                })
                cur.execute(
                    """
                    INSERT INTO application_integration (
                        application_id, kind, created_at, updated_at, configuration
                    )
                    VALUES (
                        %s, 'Http', NOW(), NOW(), %s::jsonb
                    )
                    ON CONFLICT (application_id, kind) DO UPDATE SET
                        configuration = EXCLUDED.configuration,
                        updated_at = NOW();
                    """,
                    (app_id, http_config),
                )

                # 6. Garante o Dispositivo (Sensor_Galpao_lab - d3afdcdc546af01d)
                dev_eui_hex = "d3afdcdc546af01d"
                join_eui_hex = "0000000000000000"
                cur.execute(
                    """
                    INSERT INTO device (
                        dev_eui, application_id, device_profile_id,
                        created_at, updated_at,
                        name, description, external_power_source,
                        enabled_class, skip_fcnt_check, is_disabled,
                        tags, variables, join_eui, app_layer_params, f_cnt_up
                    )
                    VALUES (
                        decode(%s, 'hex'), %s, %s,
                        NOW(), NOW(),
                        'Sensor_Galpao_lab', 'Nó Sensor LoRaWAN (MQ-135 e MQ-131)', FALSE,
                        'A', TRUE, FALSE,
                        '{}'::jsonb, '{}'::jsonb, decode(%s, 'hex'), '{}'::jsonb, 0
                    )
                    ON CONFLICT (dev_eui) DO NOTHING;
                    """,
                    (dev_eui_hex, app_id, dp_id, join_eui_hex),
                )

                # 7. Garante a chave OTAA (AppKey / NwkKey = 000102030405060708090a0b0c0d0e0f)
                key_hex = "000102030405060708090a0b0c0d0e0f"
                cur.execute(
                    """
                    INSERT INTO device_keys (
                        dev_eui, created_at, updated_at,
                        nwk_key, app_key, dev_nonces, join_nonce, gen_app_key
                    )
                    VALUES (
                        decode(%s, 'hex'), NOW(), NOW(),
                        decode(%s, 'hex'), decode(%s, 'hex'),
                        '{}'::jsonb, 0, decode('00000000000000000000000000000000', 'hex')
                    )
                    ON CONFLICT (dev_eui) DO NOTHING;
                    """,
                    (dev_eui_hex, key_hex, key_hex),
                )

        print("[CHIRPSTACK] Provisionamento automático verificado com sucesso (Gateway, Perfil, Codec JS, App, Webhook HTTP e Sensor_Galpao_lab)!")
    except Exception as e:
        print(f"[CHIRPSTACK] Erro ao verificar provisionamento: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    garantir_provisionamento_chirpstack()
