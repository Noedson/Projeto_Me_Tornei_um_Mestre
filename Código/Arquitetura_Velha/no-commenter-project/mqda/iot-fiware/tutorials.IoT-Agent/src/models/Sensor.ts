let myHeaders = new Headers();
myHeaders.append("Content-Type", "application/json");
myHeaders.append("fiware-service", "openiot");
myHeaders.append("fiware-servicepath", "/");
myHeaders.append(
  "Cookie",
  "connect.sid=s%3AmdgXLUl4tCxdyU2QqB8QJGALuxjcTSPO.R9t9QCl%2FYz1glJCiPh07gncRPHHCpgLPVLQYLZFXLo4"
);

export const createSensor = async (
  device_id: string,
  entity_name: string,
  entity_type: string,
  object_id:string,
  nameAtribute:string,
  typeAtribute:string,
  foreignkeyNameRef: string,
  foreignkeyValueRef: string
) => {
  const iotaNorthUrl = process.env.IOTA_NORTH_URL || "http://localhost:4041";
  let sensors = JSON.stringify({
    "devices":[
      {
          "device_id": `${device_id}`,
          "entity_name": `urn:ngsi-ld:${entity_name}`,
          "entity_type": `${entity_type}`,
          "transport": "HTTP",
          "attributes": [
          {
              "object_id": `${object_id}`,
              "name": `${nameAtribute}`,
              "type": `${typeAtribute}`
          }
          ],
      
          "static_attributes": [
          {
              "name": `${foreignkeyNameRef}`,
              "type": "Relationship",
              "value": `urn:ngsi-ld:${foreignkeyValueRef}`
          }
          ]
      },
  ]
  });
  let requestOptions = {
    method: "POST",
    headers: myHeaders,
    body: sensors,
    redirect: "follow" as RequestRedirect,
  };

  try {
    const response = await fetch(
      `${iotaNorthUrl}/iot/devices`,
      requestOptions
    );
    const result = await response.text();
    return { message: result };
  } catch (error) {
    return { message: error };
  }
};
