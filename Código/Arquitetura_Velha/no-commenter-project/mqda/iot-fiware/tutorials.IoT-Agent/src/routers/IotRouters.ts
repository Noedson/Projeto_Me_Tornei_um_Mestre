import {Router} from 'express'
import * as IotControllersDevices from '../controllers/IotControllers'

const ROUTER = Router()
ROUTER.get('/ping',IotControllersDevices.ping)
ROUTER.post('/create-room',IotControllersDevices.CREATE_ROOMS)
ROUTER.post('/create-service-iot',IotControllersDevices.CREATE_SERVICE_IOT)
ROUTER.post('/create-sensors',IotControllersDevices.CREATE_SENSORS)
ROUTER.post('/send-data-sensors',IotControllersDevices.SUBMIT_DATA_AGENT)
ROUTER.get('/show-all-rooms',IotControllersDevices.SHOW_ALL_ROOMS)
ROUTER.get('/show-all-docs/:idRoom',IotControllersDevices.SHOW_LAST_DOC_BY_ID_ROOM)
ROUTER.get('/show-sensors/:entity_name',IotControllersDevices.SHOW_SENSORS)


export default ROUTER