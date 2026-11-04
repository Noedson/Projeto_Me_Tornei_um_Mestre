FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git

WORKDIR /src
RUN git clone --depth 1 https://github.com/UniCT-ARSLab/LWN-Simulator.git .

# Ajusta o AU915 do LWN-Simulator para operar na Sub-banda 0 (au915_0: canais 0..7 de 125kHz e canal 64 de 500kHz),
# corrige o canal de downlink RX1 do AU915 (72 + indexChannel%8 -> 923.3..927.5 MHz) e sincroniza o canal ativo no JoinRequest.
RUN sed -i 's/EnableUplink:      group.EnableUplink,/EnableUplink:      group.EnableUplink \&\& ((group.MinDataRate == 0 \&\& i < 8) || (group.MinDataRate == 6 \&\& i == 0)),/g' simulator/components/device/regional_parameters/au915_928.go && \
    sed -i 's/indexChannel = rand.Int() % au.GetNbReservedChannels()/indexChannel = rand.Int() % 8/g' simulator/components/device/regional_parameters/au915_928.go && \
    sed -i 's/newIndexChannel := indexChannel % 8/newIndexChannel := 72 + (indexChannel % 8)/g' simulator/components/device/regional_parameters/au915_928.go && \
    sed -i 's/datarate, indexChannelUp = d.Info.Configuration.Region.SetupInfoRequest(int(d.Info.Status.IndexchannelActive))/datarate, indexChannelUp = d.Info.Configuration.Region.SetupInfoRequest(int(d.Info.Status.IndexchannelActive)); d.Info.Status.IndexchannelActive = uint16(indexChannelUp)/g' simulator/components/device/createRXPK.go

# Sobrescreve os componentes do simulador com a simulação dinâmica do event_up (Boa <-> Moderada <-> Ruim) e painel de controle IQAr
COPY overrides/ /src/

RUN go install github.com/rakyll/statik@latest && \
    go mod download && \
    cd webserver && statik -f -src=public && cd .. && \
    go build -o /src/bin/lwnsimulator cmd/main.go

FROM alpine:3.20

RUN apk add --no-cache ca-certificates tzdata

WORKDIR /app

COPY --from=builder /src/bin/lwnsimulator /app/lwnsimulator_bin
COPY config.json /app/config.json
COPY lwnsimulator/ /app/lwnsimulator/

EXPOSE 8002 8003

CMD ["/app/lwnsimulator_bin"]

