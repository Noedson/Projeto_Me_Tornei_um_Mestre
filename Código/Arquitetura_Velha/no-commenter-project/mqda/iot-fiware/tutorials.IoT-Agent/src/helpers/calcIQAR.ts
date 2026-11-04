interface IndexRange {
    indexInitial: number;
    indexFinal: number;
    concentrationInitial: number;
    concentrationFinal: number;
}

interface SensorData {
    sensorName: string;
    sensorValue: number | null;
}

const qualityLabels = ['Boa', 'Moderada', 'Ruim', 'Muito Ruim', 'Péssima'];

function getQualityLabel(index: number): string {
    if (index <= 40) return qualityLabels[0];
    if (index <= 80) return qualityLabels[1];
    if (index <= 120) return qualityLabels[2];
    if (index <= 200) return qualityLabels[3];
    return qualityLabels[4];
}
function calculateIndex(sensorValue: number, ranges: IndexRange[]): number {
    const range = ranges.find(range => sensorValue >= range.concentrationInitial && sensorValue <= range.concentrationFinal);
    if (range) {
        const { indexInitial, indexFinal, concentrationInitial, concentrationFinal } = range;
        return indexInitial + ((indexFinal - indexInitial) / (concentrationFinal - concentrationInitial)) * (sensorValue - concentrationInitial);
    } else {
        return ranges[ranges.length - 1].indexFinal;
    }
}

function roundValue(sensorValue: number): number {
    const rounded = Math.round(sensorValue);
    if (rounded % 2 !== 0 && rounded !== 500) return Math.round(sensorValue);
    return rounded;
}

export function calcIQAR(sensorData: SensorData[]): [string, Record<string, number>] {
    const iqarValues: number[] = [];
    const sensorDataObject: Record<string, number> = {};

    const indexRanges: Record<string, IndexRange[]> = {
        CO_MQ9_Level: [{ indexInitial: 0, indexFinal: 40, concentrationInitial: 0, concentrationFinal: 9 },
                        { indexInitial: 41, indexFinal: 80, concentrationInitial: 10, concentrationFinal: 11 },
                        { indexInitial: 81, indexFinal: 120, concentrationInitial: 12, concentrationFinal: 13 },
                        { indexInitial: 121, indexFinal: 200, concentrationInitial: 14, concentrationFinal: 15 },
                        { indexInitial: 201, indexFinal: 400, concentrationInitial: 16, concentrationFinal: 50 }],
        CO_MQ135_Level: [{ indexInitial: 0, indexFinal: 40, concentrationInitial: 0, concentrationFinal: 9 },
                          { indexInitial: 41, indexFinal: 80, concentrationInitial: 10, concentrationFinal: 11 },
                          { indexInitial: 81, indexFinal: 120, concentrationInitial: 12, concentrationFinal: 13 },
                          { indexInitial: 121, indexFinal: 200, concentrationInitial: 14, concentrationFinal: 15 },
                          { indexInitial: 201, indexFinal: 400, concentrationInitial: 16, concentrationFinal: 50 }],
        O3_MQ131_Level: [{ indexInitial: 0, indexFinal: 40, concentrationInitial: 0, concentrationFinal: 100 },
                          { indexInitial: 41, indexFinal: 80, concentrationInitial: 101, concentrationFinal: 130 },
                          { indexInitial: 81, indexFinal: 120, concentrationInitial: 131, concentrationFinal: 160 },
                          { indexInitial: 121, indexFinal: 200, concentrationInitial: 161, concentrationFinal: 200 },
                          { indexInitial: 201, indexFinal: 400, concentrationInitial: 201, concentrationFinal: 800 }]
    };

    for (const sensor of sensorData) {
        if (sensor.sensorName !== 'CO_MQ9_Level' && sensor.sensorName !== 'CO_MQ135_Level' && sensor.sensorName !== 'O3_MQ131_Level') {
            continue; 
        }
        if(Number.isNaN(sensor.sensorValue) || sensor.sensorValue === null){
            continue
        }

        const roundedValue = roundValue(sensor.sensorValue);
        const ranges = indexRanges[sensor.sensorName];
        const index = calculateIndex(roundedValue, ranges);
        iqarValues.push(index);
        sensorDataObject[`${sensor.sensorName}_IQAR`] = index;
    }

    const maxIndex = Math.max(...iqarValues);
    const quality = getQualityLabel(maxIndex);

    return [quality, sensorDataObject];
}
