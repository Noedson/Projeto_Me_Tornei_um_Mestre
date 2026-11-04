const qualityLabels = [
  "Cuidado: a fadiga é possível com exposição e atividade prolongadas. A atividade contínua pode resultar em cãibras causadas pelo calor.",
  "Cuidado extremo: cãibras e exaustão pelo calor são possíveis. A atividade contínua pode resultar em insolação.",
  "Perigo: cãibras e exaustão pelo calor são prováveis; a insolação é provável com atividade contínua.",
  "Perigo extremo: a insolação é iminente.",
];

export function calculateHeatIndex(tempCelsius: number, rh: number): number {
  const tempCelsiusAdjusted = tempCelsius; // Ajuste da temperatura para evitar possíveis modificações diretas
  const rhAdjusted = rh; // Ajuste da umidade relativa do ar

  if (tempCelsiusAdjusted < 26.7) {
    return 0.5 * (tempCelsiusAdjusted + 61.0 + ((tempCelsiusAdjusted - 68.0) * 1.2) + (rhAdjusted * 0.094));
  } else {
    const HI = -8.78469475556 +
      1.61139411 * tempCelsiusAdjusted +
      2.33854883889 * rhAdjusted -
      0.14611605 * tempCelsiusAdjusted * rhAdjusted -
      0.012308094 * (tempCelsiusAdjusted * tempCelsiusAdjusted) -
      0.0164248277778 * (rhAdjusted * rhAdjusted) +
      0.002211732 * (tempCelsiusAdjusted * tempCelsiusAdjusted) * rhAdjusted +
      0.00072546 * tempCelsiusAdjusted * (rhAdjusted * rhAdjusted) -
      0.000003582 * (tempCelsiusAdjusted * tempCelsiusAdjusted) * (rhAdjusted * rhAdjusted);

    if (rhAdjusted < 13 && tempCelsiusAdjusted >= 26.7 && tempCelsiusAdjusted <= 44.4) {
      return HI - ((13 - rhAdjusted) / 4) * Math.sqrt((17 - Math.abs(tempCelsiusAdjusted - 35)) / 17);
    } else if (rhAdjusted > 85 && tempCelsiusAdjusted >= 26.7 && tempCelsiusAdjusted <= 30.6) {
      return HI + ((rhAdjusted - 85) / 10) * ((30.6 - tempCelsiusAdjusted) / 5);
    } else {
      return HI;
    }
  }
}

export function targetConcept(temp: number, rh: number) {
  console.log('temp:', temp); // Exibe a temperatura no console para depuração
  console.log('rh:', rh); // Exibe a umidade no console para depuração

  if (
    (Math.round(temp) === 27 && rh >= 40 && rh <= 100) ||
    (Math.round(temp) === 28 && rh >= 40 && rh <= 85) ||
    (Math.round(temp) === 29 && rh >= 40 && rh <= 70) ||
    (Math.round(temp) === 30 && rh >= 40 && rh <= 55) ||
    (Math.round(temp) === 31 && rh < 40 && rh >= 40 && rh <= 45)
  ) {
    return qualityLabels[0]; // Retorna o rótulo "Cuidado"
  }

  else if (
    (Math.round(temp) === 28 && rh >= 90 && rh <= 100) ||
    (Math.round(temp) === 29 && rh >= 75 && rh <= 100) ||
    (Math.round(temp) === 30 && rh >= 60 && rh <= 85) ||
    (Math.round(temp) === 31 && rh >= 50 && rh <= 75) ||
    (Math.round(temp) === 32 && rh >= 40 && rh <= 65) ||
    (Math.round(temp) === 33 && rh >= 40 && rh <= 55) ||
    (Math.round(temp) === 34 && rh >= 40 && rh <= 50) ||
    (Math.round(temp) === 36 && rh <= 40)
  ) {
    return qualityLabels[1]; // Retorna o rótulo "Cuidado extremo"
  }

  else if (
    (Math.round(temp) === 30 && rh >= 90 && rh <= 100) ||
    (Math.round(temp) === 31 && rh >= 80 && rh <= 100) ||
    (Math.round(temp) === 32 && rh >= 70 && rh <= 90) ||
    (Math.round(temp) === 33 && rh >= 60 && rh <= 80) ||
    (Math.round(temp) === 34 && rh >= 55 && rh <= 75) ||
    (Math.round(temp) === 36 && rh >= 45 && rh <= 65) ||
    (Math.round(temp) === 37 && rh >= 40 && rh <= 60) ||
    (Math.round(temp) === 38 && rh >= 40 && rh <= 55) ||
    (Math.round(temp) === 39 && rh >= 40 && rh <= 50) ||
    (Math.round(temp) === 40 && rh >= 40 && rh <= 45) ||
    (Math.round(temp) === 41 && rh <= 40)
  ) {
    return qualityLabels[2]; // Retorna o rótulo "Perigo"
  }

  else if (
    (Math.round(temp) === 32 && rh >= 95 && rh <= 100) ||
    (Math.round(temp) === 33 && rh >= 85 && rh <= 90) ||
    (Math.round(temp) === 34 && rh >= 80 && rh <= 85) ||
    (Math.round(temp) === 36 && rh >= 70 && rh <= 75) ||
    (Math.round(temp) === 37 && rh >= 65 && rh <= 70) ||
    (Math.round(temp) === 38 && rh >= 60 && rh <= 65) ||
    (Math.round(temp) === 39 && rh >= 55 && rh <= 60) ||
    (Math.round(temp) === 40 && rh >= 50 && rh <= 55) ||
    (Math.round(temp) === 41 && rh >= 45 && rh <= 50) ||
    (Math.round(temp) === 42 && rh >= 40 && rh <= 45) ||
    (Math.round(temp) === 43 && rh <= 40)
  ) {
    return qualityLabels[3]; // Retorna o rótulo "Perigo extremo"
  }

  else {
    return "Não encontrado";
  }
}
