let myHeaders = new Headers();
myHeaders.append("fiware-service", "openiot");
myHeaders.append("fiware-servicepath", "/");
myHeaders.append("Cookie", "connect.sid=s%3AmdgXLUl4tCxdyU2QqB8QJGALuxjcTSPO.R9t9QCl%2FYz1glJCiPh07gncRPHHCpgLPVLQYLZFXLo4");

export const getAllSensors =  async (entity_name:string) => {
    const orionUrl = process.env.ORION_URL || "http://localhost:1026";
    let requestOptions = {
        method: 'GET',
        headers: myHeaders,
        redirect: 'follow' as RequestRedirect
      };
      try {
        const response = await fetch(`${orionUrl}/v2/entities?options=keyValues&type=${entity_name}`, requestOptions)
        const result = await response.text();
        console.log(result)
        return { success: true, message: JSON.parse(result)};
    } catch (error) {
        return { success: false, message: error };
    }
}
