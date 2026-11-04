export const getAllRooms = async (entity_name:string) => {
    const orionUrl = process.env.ORION_URL || "http://localhost:1026";
    let requestOptions = {
        method: 'GET',
        redirect: 'follow' as RequestRedirect
      };
      try {
        const response = await fetch(`${orionUrl}/v2/entities?options=keyValues&type=${entity_name}`, requestOptions)
        const result = await response.text();
        return { success: true, message:JSON.parse(result)};
    } catch (error) {
        return { success: false, message: error };
    }
  }
