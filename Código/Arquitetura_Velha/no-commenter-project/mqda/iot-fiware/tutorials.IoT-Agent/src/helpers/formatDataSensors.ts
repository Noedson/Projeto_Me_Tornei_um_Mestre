export function format (data:string,sensor_room:string):string[][] | Error{
    if (!sensor_room.includes('_') || !sensor_room.includes('-')) {
        return new Error('Formato incorreto do nome do sensor (ChirpStack). O formato correto é Ex:sensor_001-room:001');
    }
    let [sensor,id_entity] = sensor_room.split('-')
    let [name_sensor,numberId] = sensor.split('_') 
    return data
        .trim()
        .replace(/^,+|,+$/g, '')
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.includes('|'))
        .map((current) => {
            let [object_id,value] = current.split('|') 
            return (`${object_id.trim()}_${numberId} ${object_id.trim()}_Level|${value.trim()}`).split(' ')
        })
}
