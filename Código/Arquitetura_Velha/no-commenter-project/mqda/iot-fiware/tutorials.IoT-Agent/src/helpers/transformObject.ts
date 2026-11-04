//.replace(/Level$/, '');
export function transformObject(originalObject:any) {
    let entriesArray = Object.entries(originalObject);
    let newObject:any= {};
    entriesArray.forEach(([key, value]) => {
      let nameLevel:string = key
      newObject[nameLevel] = value;
    });
    return newObject;
  }

