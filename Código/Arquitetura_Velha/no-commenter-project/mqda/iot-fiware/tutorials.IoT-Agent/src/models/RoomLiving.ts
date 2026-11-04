let myHeaders = new Headers();
myHeaders.append("Content-Type", "application/json");

export const createRoom = async (id:string,name:string,description:string,block:string,level:string,campus:string,latitude:number,longitude:number) => {
    const orionUrl = process.env.ORION_URL || "http://localhost:1026";
    let raw = JSON.stringify({
        "id" : `urn:ngsi-ld:${id}`,
        "type":"LivingRoom",
        "name":{
            "type":"Text",
            "value":`${name}`
        },
        "description":{
           "type":"Text",
           "value":`${description}`
        },
        "block":{
          "type":"Text",
          "value":`${block}`
       },
        "level":{
          "type":"Text",
          "value":`${level}`
       },
       "campus":{
        "type":"Text",
        "value":`${campus}`
     },
     
     "latitude":{
      "type":"Number",
      "value":`${latitude}`
   },
     "longitude":{
     "type":"Number",
     "value":`${longitude}`
  },

    })

    let requestOptions = {
        method: 'POST',
        headers: myHeaders,
        body: raw,
        redirect: 'follow' as RequestRedirect
      };

    try {
        const response = await fetch(`${orionUrl}/v2/entities`, requestOptions)
        const result = await response.text();
        return { message: result };
      }
    catch(error){
        return { message: error };
      }

}
