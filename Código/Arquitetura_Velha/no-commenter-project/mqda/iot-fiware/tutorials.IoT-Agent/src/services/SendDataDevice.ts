let myHeaders = new Headers();
myHeaders.append("Content-Type", "text/plain");
myHeaders.append("Cookie", "connect.sid=s%3AmdgXLUl4tCxdyU2QqB8QJGALuxjcTSPO.R9t9QCl%2FYz1glJCiPh07gncRPHHCpgLPVLQYLZFXLo4");

export const sendDataAgent = async (targetDevice:string,object:string) => {
//4jggokgpepnvsb2uv4s40d59ov
    const iotaSouthUrl = process.env.IOTA_SOUTH_URL || "http://localhost:7896";
    let raw = object
      
      let requestOptions:any = {
        method: 'POST',
        headers: myHeaders,
        body: raw,
        redirect: 'follow' as RequestRedirect
      };
      try {
        const response = await fetch(`${iotaSouthUrl}/iot/d?k=4jggokgpepnvsb2uv4s40d59ov&i=${targetDevice}`, requestOptions)
        const result = await response.text();
        console.log(result)
        return { success: true };
    } catch (error) {
      console.log(error)
        return { success: false };
    }

}
