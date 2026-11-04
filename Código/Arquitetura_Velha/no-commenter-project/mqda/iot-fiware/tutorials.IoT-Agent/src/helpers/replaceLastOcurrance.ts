export function replaceLastOcurrence(string:string,oldChar:string,newChar:string){
    let lastIndex = string.lastIndexOf(oldChar)
    if(lastIndex ===-1){
        return string
    }
    let newString = string.slice(0,lastIndex) + newChar + string.slice(lastIndex + 1)
    return newString
}