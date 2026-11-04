import express,{Request,Response} from 'express'
import path from 'path'
import cors from 'cors'
import dotenv from 'dotenv'
import {createDatabase} from './db/Cloudant'
import IotRouters from './routers/IotRouters'
dotenv.config()

const server = express()
const cor_options = {
    origin: '*', 
    methods: 'GET,HEAD,PUT,PATCH,POST,DELETE', 
    credentials: true,
    optionsSuccessStatus: 200
  };

server.use(express.json())
server.use(express.urlencoded({extended:true}))
server.use(express.static(path.join(__dirname,'../public')))
server.use(cors(cor_options))
server.use(IotRouters)

createDatabase('sensors').catch(() => {});
createDatabase('rooms').catch(() => {});

server.use((req:Request,res:Response) => {
    res.status(400).json({error:'endpoint não encontrado'})
})

const port = process.env.PORT || 4000;
server.listen(port, () => {
    console.log(`>>> [Proxy de Integração FIWARE] Servidor escutando na porta ${port} (100% Local com MongoDB)`);
})
