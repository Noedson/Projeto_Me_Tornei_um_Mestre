package device

import (
	"fmt"
	"strings"

	"github.com/arslab/lwnsimulator/simulator/components/device/classes"
	up "github.com/arslab/lwnsimulator/simulator/components/device/frames/uplink"
	"github.com/arslab/lwnsimulator/simulator/util"
	"github.com/brocaar/lorawan"
)

func (d *Device) CreateUplink() [][]byte {

	var mtype lorawan.MType
	var payload lorawan.Payload
	var DataPayload []lorawan.DataPayload
	var frames [][]byte

	if d.Info.Configuration.SupportedClassB {

		if d.Info.Status.DataUplink.IsTherePingSlotInfoReq() {

			d.SwitchClass(classes.ClassA)
			d.Info.Status.DataUplink.ClassB = false

		} else if d.Class.GetClass() == classes.ClassB {
			d.Info.Status.DataUplink.ClassB = true
		}

	} else {
		d.Info.Status.DataUplink.ClassB = false
	}

	switch d.Info.Status.Mode {
	case util.Retransmission:
		return d.Info.Status.LastUplinks

	case util.Normal: //new uplink

		if len(d.Info.Status.BufferUplinks) > 0 {

			mtype = d.Info.Status.BufferUplinks[0].MType
			payload = d.Info.Status.BufferUplinks[0].Payload

			switch len(d.Info.Status.BufferUplinks) {
			case 1:
				d.Info.Status.BufferUplinks = d.Info.Status.BufferUplinks[:0]

			default:
				d.Info.Status.BufferUplinks = d.Info.Status.BufferUplinks[1:]

			}

		} else {
			payloadStr, iqarInfo := NextIQArPayload()
			d.Info.Status.Payload = &lorawan.DataPayload{
				Bytes: []byte(payloadStr),
			}
			mtype = d.Info.Status.MType
			payload = d.Info.Status.Payload

			msg := fmt.Sprintf("[Simulador event_up | Alvo: %s | Atual: %s (%d/%d) | CO=%.2f ppm] %s",
				strings.ToUpper(iqarInfo.Target),
				strings.ToUpper(iqarInfo.CurrentClass),
				iqarInfo.Step,
				iqarInfo.TotalSteps,
				iqarInfo.CO,
				payloadStr,
			)
			d.Print(msg, nil, util.PrintBoth)
			d.Console.PrintSocket("iqar-status", iqarInfo)
		}

		d.Info.Status.LastMType = mtype

	}

	// Garante que sem ADR (ou caso o DataRate tenha caído abaixo de DR4 no AU915),
	// o DataRate permaneça em DataRateInitial (DR5 = SF7BW125, até 242 bytes) para nunca
	// fragmentar o payload CSV nem retornar tamanho 0 (o que impedia o envio ao ChirpStack).
	if !d.Info.Configuration.SupportedADR || d.Info.Status.DataRate < 4 {
		if d.Info.Configuration.DataRateInitial >= 4 {
			d.Info.Status.DataRate = d.Info.Configuration.DataRateInitial
		} else {
			d.Info.Status.DataRate = 5
		}
		d.Info.Status.DataUplink.ADR.ADRACKCnt = 0
	}

	m, n := d.Info.Configuration.Region.GetPayloadSize(d.Info.Status.DataRate, d.Info.Status.DataUplink.DwellTime)
	if m <= 0 || n <= 0 {
		m, n = 250, 242
	}

	if d.Info.Configuration.SupportedFragment { //frammentazione

		if len(d.Info.Status.DataUplink.FOpts) > 0 {
			DataPayload = up.Fragmentation(n, payload)
		} else {
			DataPayload = up.Fragmentation(m, payload)
		}

	} else { //troncamento

		if len(d.Info.Status.DataUplink.FOpts) > 0 {
			DataPayload = append(DataPayload, up.Truncate(n, payload))
		} else {
			DataPayload = append(DataPayload, up.Truncate(m, payload))
		}

	}

	for i := 0; i < len(DataPayload); i++ {

		frame, err := d.Info.Status.DataUplink.GetFrame(mtype, DataPayload[i], d.Info.DevAddr, d.Info.AppSKey, d.Info.NwkSKey, false)
		if err != nil {
			d.Print("", err, util.PrintBoth)
			continue
		}
		if !d.Info.Configuration.SupportedADR {
			d.Info.Status.DataUplink.ADR.ADRACKCnt = 0
		}

		frames = append(frames, frame)
	}

	d.Info.Status.LastUplinks = frames

	return frames
}

func (d *Device) CreateACK() []byte {

	var emptyPayload lorawan.DataPayload

	frame, err := d.Info.Status.DataUplink.GetFrame(lorawan.UnconfirmedDataUp, emptyPayload, d.Info.DevAddr, d.Info.AppSKey, d.Info.NwkSKey, true)
	if err != nil {
		d.Print("", err, util.PrintBoth)
		return []byte{}
	}

	return frame

}

func (d *Device) CreateEmptyFrame() []byte {

	var emptyPayload lorawan.DataPayload

	frame, err := d.Info.Status.DataUplink.GetFrame(lorawan.UnconfirmedDataUp, emptyPayload, d.Info.DevAddr, d.Info.AppSKey, d.Info.NwkSKey, false)
	if err != nil {
		d.Print("", err, util.PrintBoth)
		return []byte{}
	}

	return frame

}

func (d *Device) SendEmptyFrame() {

	emptyFrame := d.CreateEmptyFrame()
	info := d.SetInfo(emptyFrame, false)

	d.Class.SendData(info)

	d.Print("Empty Frame sent", nil, util.PrintBoth)
}

func (d *Device) SendAck() {

	ack := d.CreateACK()
	info := d.SetInfo(ack, false)

	d.Class.SendData(info)

	d.Print("ACK sent", nil, util.PrintBoth)
}

func (d *Device) SendJoinRequest() {
	if d.Info.Configuration.DataRateInitial >= 4 {
		d.Info.Status.DataRate = d.Info.Configuration.DataRateInitial
	} else {
		d.Info.Status.DataRate = 5
	}
	d.Info.Status.DataUplink.ADR.ADRACKCnt = 0

	JoinRequest := d.CreateJoinRequest()
	info := d.SetInfo(JoinRequest, true)

	d.Class.SendData(info)
	d.Print("JOIN REQUEST sent", nil, util.PrintBoth)
}

