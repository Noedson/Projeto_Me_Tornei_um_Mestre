interface AcelerometroProps {
  titulo: string
  valor: number | null | undefined
  max: number
  unidade?: string
  corFixa?: string
  formatarValor?: (valor: number) => string
}

export function Acelerometro({ titulo, valor, max, unidade = '', corFixa, formatarValor }: AcelerometroProps) {
  const temDado = valor !== null && valor !== undefined && !Number.isNaN(Number(valor))
  const num = temDado ? Number(valor) : 0
  const pct = Math.max(0, Math.min(1, num / max))
  const angulo = -90 + pct * 180

  const raio = 52
  const comprimentoArco = Math.PI * raio
  const offset = comprimentoArco * (1 - pct)

  const cor = corFixa
    ? corFixa
    : pct >= 0.8
      ? '#ef4444'
      : pct >= 0.5
        ? '#f59e0b'
        : '#10b981'

  return (
    <div className="acelerometro-card">
      <span className="acelerometro-titulo">{titulo}</span>
      <svg viewBox="0 0 140 84" className="acelerometro-svg" aria-label={titulo}>
        {/* Trilha de fundo */}
        <path
          d="M 18 72 A 52 52 0 0 1 122 72"
          fill="none"
          stroke="var(--border)"
          strokeWidth="10"
          strokeLinecap="round"
        />
        {/* Arco preenchido */}
        <path
          d="M 18 72 A 52 52 0 0 1 122 72"
          fill="none"
          stroke={temDado ? cor : 'var(--border)'}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={comprimentoArco}
          strokeDashoffset={temDado ? offset : comprimentoArco}
          style={{ transition: 'stroke-dashoffset 0.5s ease-out, stroke 0.3s ease' }}
        />
        {/* Ponteiro */}
        <g
          style={{
            transform: `rotate(${temDado ? angulo : -90}deg)`,
            transformOrigin: '70px 72px',
            transition: 'transform 0.5s ease-out',
          }}
        >
          <line
            x1="70"
            y1="72"
            x2="70"
            y2="25"
            stroke="var(--text-h)"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
        </g>
        {/* Pino central */}
        <circle cx="70" cy="72" r="4.5" fill="var(--text-h)" />
      </svg>
      <strong className="acelerometro-valor">
        {temDado ? (formatarValor ? formatarValor(num) : `${num.toFixed(2)} ${unidade}`.trim()) : '--'}
      </strong>
    </div>
  )
}
