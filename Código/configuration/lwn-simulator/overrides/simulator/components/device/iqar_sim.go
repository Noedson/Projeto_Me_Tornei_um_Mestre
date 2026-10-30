package device

import (
	"fmt"
	"strings"
	"sync"
)

// EventUpSample representa uma leitura real extraída do event_up.csv
type EventUpSample struct {
	CO     float64 `json:"co"`
	CO2    float64 `json:"co2"`
	Alcool float64 `json:"alcool"`
	Aceton float64 `json:"aceton"`
	Toluen float64 `json:"toluen"`
	MH4    float64 `json:"mh4"`
	O3     float64 `json:"o3"`
	Classe string  `json:"classe"`
}

// IQArStatusInfo informa o estado atual da simulação de IQAr para a API e WebUI
type IQArStatusInfo struct {
	Target       string  `json:"target"`
	CurrentClass string  `json:"currentClass"`
	Phase        string  `json:"phase"`
	Step         int     `json:"step"`
	TotalSteps   int     `json:"totalSteps"`
	CO           float64 `json:"co"`
	CO2          float64 `json:"co2"`
	MH4          float64 `json:"mh4"`
	Aceton       float64 `json:"aceton"`
	Alcool       float64 `json:"alcool"`
	Toluen       float64 `json:"toluen"`
	O3           float64 `json:"o3"`
	Payload      string  `json:"payload"`
}

// Trajetória de 55 leituras reais do event_up.csv ordenadas suavemente:
// - Índices 0..15  (16 amostras): Qualidade do Ar BOA (CO < 4.5 ppm)
// - Índices 16..39 (24 amostras): Qualidade do Ar MODERADA (4.5 <= CO < 9.5 ppm)
// - Índices 40..54 (15 amostras): Qualidade do Ar RUIM (CO >= 9.5 ppm)
var EventUpTrajectory = []EventUpSample{
	{CO: 1.76, CO2: 1.58, Alcool: 0.69, Aceton: 0.23, Toluen: 0.27, MH4: 2.61, O3: 0.76, Classe: "Boa"},      // [0]
	{CO: 1.83, CO2: 1.63, Alcool: 0.71, Aceton: 0.24, Toluen: 0.28, MH4: 2.67, O3: 0.77, Classe: "Boa"},      // [1]
	{CO: 1.90, CO2: 1.67, Alcool: 0.73, Aceton: 0.25, Toluen: 0.29, MH4: 2.73, O3: 0.74, Classe: "Boa"},      // [2]
	{CO: 1.99, CO2: 1.73, Alcool: 0.76, Aceton: 0.26, Toluen: 0.30, MH4: 2.81, O3: 0.90, Classe: "Boa"},      // [3]
	{CO: 2.06, CO2: 1.78, Alcool: 0.78, Aceton: 0.27, Toluen: 0.31, MH4: 2.88, O3: 0.91, Classe: "Boa"},      // [4]
	{CO: 2.17, CO2: 1.85, Alcool: 0.82, Aceton: 0.28, Toluen: 0.33, MH4: 2.98, O3: 0.80, Classe: "Boa"},      // [5]
	{CO: 2.24, CO2: 1.89, Alcool: 0.84, Aceton: 0.29, Toluen: 0.34, MH4: 3.04, O3: 0.70, Classe: "Boa"},      // [6]
	{CO: 2.31, CO2: 1.93, Alcool: 0.86, Aceton: 0.30, Toluen: 0.34, MH4: 3.09, O3: 0.79, Classe: "Boa"},      // [7]
	{CO: 2.46, CO2: 2.02, Alcool: 0.90, Aceton: 0.31, Toluen: 0.36, MH4: 3.22, O3: 0.71, Classe: "Boa"},      // [8]
	{CO: 2.65, CO2: 2.13, Alcool: 0.96, Aceton: 0.33, Toluen: 0.39, MH4: 3.37, O3: 0.71, Classe: "Boa"},      // [9]
	{CO: 2.88, CO2: 2.26, Alcool: 1.03, Aceton: 0.36, Toluen: 0.42, MH4: 3.55, O3: 0.90, Classe: "Boa"},      // [10]
	{CO: 3.11, CO2: 2.40, Alcool: 1.10, Aceton: 0.38, Toluen: 0.45, MH4: 3.73, O3: 0.88, Classe: "Boa"},      // [11]
	{CO: 3.38, CO2: 2.54, Alcool: 1.17, Aceton: 0.41, Toluen: 0.48, MH4: 3.93, O3: 0.73, Classe: "Boa"},      // [12]
	{CO: 3.56, CO2: 2.64, Alcool: 1.22, Aceton: 0.43, Toluen: 0.50, MH4: 4.06, O3: 0.83, Classe: "Boa"},      // [13]
	{CO: 3.96, CO2: 2.85, Alcool: 1.33, Aceton: 0.47, Toluen: 0.55, MH4: 4.34, O3: 0.91, Classe: "Boa"},      // [14]
	{CO: 4.24, CO2: 3.00, Alcool: 1.41, Aceton: 0.50, Toluen: 0.59, MH4: 4.53, O3: 0.88, Classe: "Boa"},      // [15]
	{CO: 4.55, CO2: 3.16, Alcool: 1.49, Aceton: 0.53, Toluen: 0.62, MH4: 4.74, O3: 0.70, Classe: "Moderada"}, // [16]
	{CO: 4.96, CO2: 3.36, Alcool: 1.60, Aceton: 0.57, Toluen: 0.67, MH4: 5.00, O3: 0.90, Classe: "Moderada"}, // [17]
	{CO: 5.36, CO2: 3.56, Alcool: 1.70, Aceton: 0.61, Toluen: 0.72, MH4: 5.25, O3: 0.91, Classe: "Moderada"}, // [18]
	{CO: 5.82, CO2: 3.77, Alcool: 1.81, Aceton: 0.65, Toluen: 0.77, MH4: 5.53, O3: 0.85, Classe: "Moderada"}, // [19]
	{CO: 5.99, CO2: 3.85, Alcool: 1.86, Aceton: 0.67, Toluen: 0.79, MH4: 5.63, O3: 0.85, Classe: "Moderada"}, // [20]
	{CO: 6.12, CO2: 3.92, Alcool: 1.89, Aceton: 0.68, Toluen: 0.81, MH4: 5.70, O3: 0.85, Classe: "Moderada"}, // [21]
	{CO: 6.28, CO2: 3.99, Alcool: 1.93, Aceton: 0.70, Toluen: 0.83, MH4: 5.80, O3: 0.84, Classe: "Moderada"}, // [22]
	{CO: 6.38, CO2: 4.04, Alcool: 1.96, Aceton: 0.71, Toluen: 0.84, MH4: 5.86, O3: 0.83, Classe: "Moderada"}, // [23]
	{CO: 6.49, CO2: 4.09, Alcool: 1.98, Aceton: 0.72, Toluen: 0.85, MH4: 5.92, O3: 0.82, Classe: "Moderada"}, // [24]
	{CO: 6.63, CO2: 4.15, Alcool: 2.02, Aceton: 0.73, Toluen: 0.87, MH4: 6.00, O3: 0.71, Classe: "Moderada"}, // [25]
	{CO: 6.77, CO2: 4.21, Alcool: 2.05, Aceton: 0.74, Toluen: 0.88, MH4: 6.08, O3: 0.80, Classe: "Moderada"}, // [26]
	{CO: 6.88, CO2: 4.27, Alcool: 2.08, Aceton: 0.75, Toluen: 0.89, MH4: 6.14, O3: 0.88, Classe: "Moderada"}, // [27]
	{CO: 7.00, CO2: 4.32, Alcool: 2.11, Aceton: 0.76, Toluen: 0.91, MH4: 6.21, O3: 0.87, Classe: "Moderada"}, // [28]
	{CO: 7.15, CO2: 4.38, Alcool: 2.14, Aceton: 0.78, Toluen: 0.92, MH4: 6.29, O3: 0.74, Classe: "Moderada"}, // [29]
	{CO: 7.27, CO2: 4.44, Alcool: 2.17, Aceton: 0.79, Toluen: 0.94, MH4: 6.36, O3: 0.82, Classe: "Moderada"}, // [30]
	{CO: 7.41, CO2: 4.50, Alcool: 2.21, Aceton: 0.80, Toluen: 0.95, MH4: 6.44, O3: 0.77, Classe: "Moderada"}, // [31]
	{CO: 7.54, CO2: 4.56, Alcool: 2.24, Aceton: 0.81, Toluen: 0.97, MH4: 6.51, O3: 0.82, Classe: "Moderada"}, // [32]
	{CO: 7.67, CO2: 4.62, Alcool: 2.27, Aceton: 0.83, Toluen: 0.98, MH4: 6.57, O3: 0.82, Classe: "Moderada"}, // [33]
	{CO: 7.86, CO2: 4.70, Alcool: 2.31, Aceton: 0.84, Toluen: 1.01, MH4: 6.68, O3: 0.88, Classe: "Moderada"}, // [34]
	{CO: 8.03, CO2: 4.77, Alcool: 2.35, Aceton: 0.86, Toluen: 1.02, MH4: 6.77, O3: 0.87, Classe: "Moderada"}, // [35]
	{CO: 8.23, CO2: 4.86, Alcool: 2.40, Aceton: 0.88, Toluen: 1.05, MH4: 6.87, O3: 0.89, Classe: "Moderada"}, // [36]
	{CO: 8.56, CO2: 5.00, Alcool: 2.48, Aceton: 0.91, Toluen: 1.08, MH4: 7.04, O3: 0.78, Classe: "Moderada"}, // [37]
	{CO: 8.87, CO2: 5.13, Alcool: 2.55, Aceton: 0.93, Toluen: 1.12, MH4: 7.20, O3: 0.91, Classe: "Moderada"}, // [38]
	{CO: 9.23, CO2: 5.28, Alcool: 2.63, Aceton: 0.97, Toluen: 1.16, MH4: 7.38, O3: 0.77, Classe: "Moderada"}, // [39]
	{CO: 9.55, CO2: 5.41, Alcool: 2.71, Aceton: 1.00, Toluen: 1.19, MH4: 7.54, O3: 0.70, Classe: "Ruim"},     // [40]
	{CO: 9.87, CO2: 5.54, Alcool: 2.78, Aceton: 1.02, Toluen: 1.23, MH4: 7.70, O3: 0.71, Classe: "Ruim"},     // [41]
	{CO: 10.28, CO2: 5.71, Alcool: 2.87, Aceton: 1.06, Toluen: 1.27, MH4: 7.90, O3: 0.91, Classe: "Ruim"},    // [42]
	{CO: 10.62, CO2: 5.85, Alcool: 2.95, Aceton: 1.09, Toluen: 1.31, MH4: 8.07, O3: 0.81, Classe: "Ruim"},    // [43]
	{CO: 10.97, CO2: 5.99, Alcool: 3.03, Aceton: 1.12, Toluen: 1.35, MH4: 8.23, O3: 0.74, Classe: "Ruim"},    // [44]
	{CO: 11.43, CO2: 6.17, Alcool: 3.13, Aceton: 1.16, Toluen: 1.39, MH4: 8.44, O3: 0.92, Classe: "Ruim"},    // [45]
	{CO: 11.81, CO2: 6.31, Alcool: 3.21, Aceton: 1.19, Toluen: 1.43, MH4: 8.62, O3: 0.83, Classe: "Ruim"},    // [46]
	{CO: 12.00, CO2: 6.39, Alcool: 3.26, Aceton: 1.21, Toluen: 1.45, MH4: 8.71, O3: 0.91, Classe: "Ruim"},    // [47]
	{CO: 12.32, CO2: 6.51, Alcool: 3.33, Aceton: 1.24, Toluen: 1.49, MH4: 8.85, O3: 0.90, Classe: "Ruim"},    // [48]
	{CO: 12.59, CO2: 6.62, Alcool: 3.39, Aceton: 1.26, Toluen: 1.52, MH4: 8.98, O3: 0.71, Classe: "Ruim"},    // [49]
	{CO: 12.90, CO2: 6.74, Alcool: 3.45, Aceton: 1.29, Toluen: 1.55, MH4: 9.11, O3: 0.88, Classe: "Ruim"},    // [50]
	{CO: 13.28, CO2: 6.88, Alcool: 3.53, Aceton: 1.32, Toluen: 1.59, MH4: 9.28, O3: 0.74, Classe: "Ruim"},    // [51]
	{CO: 13.58, CO2: 6.99, Alcool: 3.60, Aceton: 1.35, Toluen: 1.62, MH4: 9.41, O3: 0.90, Classe: "Ruim"},    // [52]
	{CO: 13.98, CO2: 7.14, Alcool: 3.68, Aceton: 1.38, Toluen: 1.66, MH4: 9.59, O3: 0.91, Classe: "Ruim"},    // [53]
	{CO: 14.15, CO2: 7.20, Alcool: 3.72, Aceton: 1.39, Toluen: 1.68, MH4: 9.66, O3: 0.81, Classe: "Ruim"},    // [54]
}

var (
	iqarMu         sync.Mutex
	iqarTarget     = "boa" // "boa" ou "ruim"
	iqarCurrentIdx = 0
	iqarOscDir     = 1
)

func formatSamplePayload(s EventUpSample) string {
	return fmt.Sprintf(",CO_MQ135|%.2f,CO2_MQ135|%.2f,Alcool_MQ135|%.2f,Aceton_MQ135|%.2f,Toluen_MQ135|%.2f,MH4_MQ135|%.2f,O3_MQ131|%.2f",
		s.CO, s.CO2, s.Alcool, s.Aceton, s.Toluen, s.MH4, s.O3)
}

func buildStatusLocked() IQArStatusInfo {
	n := len(EventUpTrajectory)
	if iqarCurrentIdx < 0 {
		iqarCurrentIdx = 0
	}
	if iqarCurrentIdx >= n {
		iqarCurrentIdx = n - 1
	}
	s := EventUpTrajectory[iqarCurrentIdx]
	phase := "Estabilizado em Qualidade BOA"
	if iqarTarget == "ruim" {
		if iqarCurrentIdx < 47 {
			phase = "Subindo gradativamente (Boa -> Moderada -> Ruim)"
		} else {
			phase = "Estabilizado em Qualidade RUIM"
		}
	} else {
		if iqarCurrentIdx > 7 {
			phase = "Abaixando gradativamente (Ruim -> Moderada -> Boa)"
		} else {
			phase = "Estabilizado em Qualidade BOA"
		}
	}
	return IQArStatusInfo{
		Target:       iqarTarget,
		CurrentClass: s.Classe,
		Phase:        phase,
		Step:         iqarCurrentIdx + 1,
		TotalSteps:   n,
		CO:           s.CO,
		CO2:          s.CO2,
		MH4:          s.MH4,
		Aceton:       s.Aceton,
		Alcool:       s.Alcool,
		Toluen:       s.Toluen,
		O3:           s.O3,
		Payload:      formatSamplePayload(s),
	}
}

// GetIQArStatus retorna o estado atual da simulação do event_up sem avançar o passo
func GetIQArStatus() IQArStatusInfo {
	iqarMu.Lock()
	defer iqarMu.Unlock()
	return buildStatusLocked()
}

// SetIQArTarget define o alvo ("boa" ou "ruim") para a transição gradual do event_up
func SetIQArTarget(target string) IQArStatusInfo {
	iqarMu.Lock()
	defer iqarMu.Unlock()
	t := strings.ToLower(strings.TrimSpace(target))
	if t == "ruim" {
		iqarTarget = "ruim"
		iqarOscDir = 1
	} else {
		iqarTarget = "boa"
		iqarOscDir = -1
	}
	return buildStatusLocked()
}

// NextIQArPayload avança um passo na simulação gradual do event_up e retorna o payload e o status
func NextIQArPayload() (string, IQArStatusInfo) {
	iqarMu.Lock()
	defer iqarMu.Unlock()

	n := len(EventUpTrajectory)
	if iqarTarget == "ruim" {
		if iqarCurrentIdx < 47 {
			// Sobe gradativamente: Boa (0..15) -> Moderada (16..39) -> Ruim (40..47)
			iqarCurrentIdx++
		} else {
			// Oscila naturalmente dentro da faixa Ruim (47..54) para manter leituras realistas
			iqarCurrentIdx += iqarOscDir
			if iqarCurrentIdx >= n-1 {
				iqarCurrentIdx = n - 1
				iqarOscDir = -1
			} else if iqarCurrentIdx <= 47 {
				iqarCurrentIdx = 47
				iqarOscDir = 1
			}
		}
	} else {
		if iqarCurrentIdx > 7 {
			// Abaixa gradativamente: Ruim (54..40) -> Moderada (39..16) -> Boa (15..7)
			iqarCurrentIdx--
		} else {
			// Oscila naturalmente dentro da faixa Boa (0..7) para manter leituras realistas
			iqarCurrentIdx += iqarOscDir
			if iqarCurrentIdx >= 7 {
				iqarCurrentIdx = 7
				iqarOscDir = -1
			} else if iqarCurrentIdx <= 0 {
				iqarCurrentIdx = 0
				iqarOscDir = 1
			}
		}
	}

	status := buildStatusLocked()
	return status.Payload, status
}

