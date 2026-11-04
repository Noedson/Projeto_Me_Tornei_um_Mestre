
import { StorageTargetRoom,RoomType } from "../db/Cloudant";
export function closestDateTime(storageTargetRoom:RoomType) {
    const currentDate = new Date();
    let closestDateTime = null as any;
    let minDifference = Infinity;
        if(Array.isArray(storageTargetRoom)){
            storageTargetRoom.forEach((room:RoomType) => {
                const joinedDateTimeParts = room.joined.split(',');
                const joinedDateParts = joinedDateTimeParts[0].split('/');
                const joinedTimeParts = joinedDateTimeParts[1].split(':');
        
                const joinedDate = new Date(
                    parseInt(joinedDateParts[2]),  
                    parseInt(joinedDateParts[1]) - 1,  
                    parseInt(joinedDateParts[0]),  
                    parseInt(joinedTimeParts[0]), 
                    parseInt(joinedTimeParts[1])  
                );
        
                const difference = Math.abs(currentDate.getTime() - joinedDate.getTime());
        
                if (difference < minDifference) {
                    minDifference = difference;
                    closestDateTime = room;
                }
            });
        
            console.log('Data mais próxima da atual:', closestDateTime?.joined);
            console.log('Objeto com data mais próxima:', closestDateTime);
            console.log('Data atual:', currentDate.toLocaleDateString());
            console.log('Horas e minutos atuais:', currentDate.getHours(), currentDate.getMinutes());
            return closestDateTime
        
        }
        
   
}

