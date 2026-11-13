import { useEffect, useState } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts';
import { Acelerometro } from './components/Acelerometro';
import './App.css'


const API_BASE = "http://localhost:9090"

interface ConexaoInfo {
  url: string
  online: boolean
  usar_agente: number
  ultimo_sync: string | null
}

interface DashBoardData {
  conexoes: {
    Arquitetura_Nova: ConexaoInfo
    Arquitetura_Velha: ConexaoInfo
  }
  atual?: {
    Arquitetura_Nova?: any
    Arquitetura_Velha?: any
  }
  janela?: string
  historico: {
    Arquitetura_Nova: any[]
    Arquitetura_Velha: any[]
  }
  resumo_recursos: any[]
  resumo_leituras: any[]
  ultimas_leituras: any[]
}

const JANELAS = [
  { id: '5m', label: 'Tempo Real (5 min)' },
  { id: '1h', label: '1 hora' },
  { id: '24h', label: '24 horas' },
  { id: '7d', label: '7 dias' },
  { id: '15d', label: '15 dias' },
]

function App() {
  const [dados, settDados] = useState<DashBoardData | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [ultimaAtualizacao, setUltimaAtualizacao] = useState<string>('--')
  const [carregando, setCarregando] = useState<boolean>(false)
  const [janela, setJanela] = useState<string>('5m')

  //1. Busca os dados do PostgreSQL Central em busca de 3 segundo

  const formatarTamanhoMB = (mb: number) => {
    if (!mb || mb <= 0) return '0.00 KB'
    if (mb < 1) return `${(mb * 1024).toFixed(2)} KB`
    if (mb < 1024) return `${mb.toFixed(2)} MB`
    return `${(mb / 1024).toFixed(2)} GB`
  }

  const formatarVelocidadeKBps = (kbps: number) => {
    if (!kbps || kbps <= 0) return '0.00 KB/s'
    if (kbps < 1) return `${(kbps * 1024).toFixed(0)} B/s`
    if (kbps < 1024) return `${kbps.toFixed(2)} KB/s`
    if (kbps < 1024 * 1024) return `${(kbps / 1024).toFixed(2)} MB/s`
    return `${(kbps / (1024 * 1024)).toFixed(2)} GB/s`
  }

  const formatarDataHora = (iso: any, incluirAno = false) => {
    if (!iso) return '--'
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return String(iso)
    return d.toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      ...(incluirAno ? { year: 'numeric' } : {}),
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  const buscarDados = async (janelaAlvo = janela) => {
    try {
      const resp = await fetch(`${API_BASE}/api/dashboard?janela=${janelaAlvo}`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const json = await resp.json()
      setUltimaAtualizacao(new Date().toLocaleString('pt-BR'))
      settDados(json)
      setErro(null)
    } catch (err: any) {
      setErro('Aguardando conexão com a API Central (porta 9090')
    }
  }

  useEffect(() => {
    buscarDados(janela)
    const timer = setInterval(() => buscarDados(janela), 2000)
    return () => clearInterval(timer)
  }, [janela])

  //2. Liga e desliga o Agente(em uma maquina ou nas duas)

  const alternarAgente = async (alvo: string, novoEstado: number) => {
    setCarregando(true)
    try {
      await fetch(`${API_BASE}/api/controle-agente`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alvo, usar_agente: novoEstado }),
      })
      await buscarDados()
    } finally {
      setCarregando(false)
    }
  }

  const nova = dados?.conexoes?.Arquitetura_Nova
  const velha = dados?.conexoes?.Arquitetura_Velha
  const histVelha = dados?.historico?.Arquitetura_Velha || []
  const histNova = dados?.historico?.Arquitetura_Nova || []
  const maxPontos = Math.max(histVelha.length, histNova.length)
  const dadosComparativos = Array.from({ length: maxPontos }, (_, idx) => {
    const offset = maxPontos - 1 - idx
    const v = histVelha[histVelha.length - 1 - offset]
    const n = histNova[histNova.length - 1 - offset]
    return {
      timestamp: n?.timestamp || v?.timestamp,
      cpu_velha: v ? Number(v.cpu_percent) : null,
      cpu_nova: n ? Number(n.cpu_percent) : null,
      ram_velha: v ? Number(v.mem_usage_mb) : null,
      ram_nova: n ? Number(n.mem_usage_mb) : null,
      rede_velha: v ? Number(v.net_rx_kbps) : null,
      rede_nova: n ? Number(n.net_rx_kbps) : null,
      agente_velha: v ? Number(v.usar_agente) : null,
      agente_nova: n ? Number(n.usar_agente) : null,
    }
  })

  const extrairMarcadoresAgente = (lista: any[], campo = 'usar_agente', prefixo = 'Agente') => {
    const marcadores: { timestamp: string; label: string; cor: string }[] = []
    for (let i = 1; i < lista.length; i++) {
      const ant = lista[i - 1]?.[campo]
      const atual = lista[i]?.[campo]
      if (
        ant !== null &&
        ant !== undefined &&
        atual !== null &&
        atual !== undefined &&
        Number(ant) !== Number(atual)
      ) {
        const ligado = Number(atual) === 1
        marcadores.push({
          timestamp: lista[i].timestamp,
          label: `${ligado ? '🤖' : '⚡'} ${prefixo} ${ligado ? 'ON' : 'OFF'}`,
          cor: ligado ? '#10b981' : '#ef4444',
        })
      }
    }
    return marcadores
  }

  const marcadoresVelha = extrairMarcadoresAgente(histVelha, 'usar_agente', 'Agente')
  const marcadoresNova = extrairMarcadoresAgente(histNova, 'usar_agente', 'Agente')
  const marcadoresComparativos = [
    ...extrairMarcadoresAgente(dadosComparativos, 'agente_velha', 'Velha'),
    ...extrairMarcadoresAgente(dadosComparativos, 'agente_nova', 'Nova'),
  ]

  const renderMarcadores = (marcadores: { timestamp: string; label: string; cor: string }[]) =>
    marcadores.map((m, idx) => (
      <ReferenceLine
        key={`${m.timestamp}-${m.label}-${idx}`}
        x={m.timestamp}
        stroke={m.cor}
        strokeDasharray="4 4"
        strokeWidth={2}
        label={{ value: m.label, position: 'insideTopRight', fill: m.cor, fontSize: 11, fontWeight: 700 }}
      />
    ))
  const velhaAtual = velha?.online ? (dados?.atual?.Arquitetura_Velha || histVelha[histVelha.length - 1]) : null
  const novaAtual = nova?.online ? (dados?.atual?.Arquitetura_Nova || histNova[histNova.length - 1]) : null
  return (
    <div className="painel-container">
      <header className="painel-header">
        <div>
          <h1>Monitoramento Experimental — Dissertação de Mestrado</h1>
          <p>Comparativo: Arquitetura Velha (FIWARE) vs. Arquitetura Nova (Django) | Com e Sem Agente IA V4</p>
          <span className="badge-ao-vivo">🟢 Ao vivo · Atualizado às {ultimaAtualizacao}</span>
        </div>
        <div className="botoes-globais">
          <button
            disabled={carregando}
            className="btn btn-ativar"
            onClick={() => alternarAgente('ambas', 1)}
          >
            Ligar Agente nas 2 Máquinas (Etapa 2)
          </button>
          <button
            disabled={carregando}
            className="btn btn-desativar"
            onClick={() => alternarAgente('ambas', 0)}
          >
            Desligar Agente nas 2 Máquinas (Etapa 1)
          </button>
        </div>
      </header>
      {erro && <div className="alerta-erro">{erro}</div>}
      {/* Cards de Status das 2 Máquinas */}
      <section className="grid-maquinas">
        <div className="card-maquina">
          <h2>Máquina 1: Arquitetura Velha (FIWARE + Node-RED + Mongo)</h2>
          <p>Status: <strong>{velha?.online ? '🟢 Online' : '🔴 Offline'}</strong> | Último Sync: {velha?.ultimo_sync || '--'}</p>
          <p>Modo Atual: <strong>{velha?.usar_agente === 1 ? '🤖 COM AGENTE IA' : '⚡ SEM AGENTE (Reativo)'}</strong></p>
          <div className="metricas-instantaneas">
            <Acelerometro titulo="CPU" valor={velhaAtual?.cpu_percent} max={100} unidade="%" />
            <Acelerometro titulo="RAM" valor={velhaAtual?.mem_usage_mb} max={4096} corFixa="#a855f7" formatarValor={formatarTamanhoMB} />
            <Acelerometro titulo="Rede RX" valor={velhaAtual?.net_rx_kbps} max={3072} corFixa="#f59e0b" formatarValor={formatarVelocidadeKBps} />
            <Acelerometro titulo="Rede TX" valor={velhaAtual?.net_tx_kbps} max={3072} corFixa="#ef4444" formatarValor={formatarVelocidadeKBps} />
          </div>
          <button
            disabled={carregando}
            className="btn"
            onClick={() => alternarAgente('Arquitetura_Velha', velha?.usar_agente === 1 ? 0 : 1)}
          >
            {velha?.usar_agente === 1 ? 'Desligar Agente na Velha' : 'Ligar Agente na Velha'}
          </button>
        </div>
        <div className="card-maquina">
          <h2>Máquina 2: Arquitetura Nova (Django + PostgreSQL)</h2>
          <p>Status: <strong>{nova?.online ? '🟢 Online' : '🔴 Offline'}</strong> | Último Sync: {nova?.ultimo_sync || '--'}</p>
          <p>Modo Atual: <strong>{nova?.usar_agente === 1 ? '🤖 COM AGENTE IA' : '⚡ SEM AGENTE (Reativo)'}</strong></p>
          <div className="metricas-instantaneas">
            <Acelerometro titulo="CPU" valor={novaAtual?.cpu_percent} max={100} unidade="%" />
            <Acelerometro titulo="RAM" valor={novaAtual?.mem_usage_mb} max={4096} corFixa="#06b6d4" formatarValor={formatarTamanhoMB} />
            <Acelerometro titulo="Rede RX" valor={novaAtual?.net_rx_kbps} max={3072} corFixa="#10b981" formatarValor={formatarVelocidadeKBps} />
            <Acelerometro titulo="Rede TX" valor={novaAtual?.net_tx_kbps} max={3072} corFixa="#3b82f6" formatarValor={formatarVelocidadeKBps} />
          </div>
          <button
            disabled={carregando}
            className="btn"
            onClick={() => alternarAgente('Arquitetura_Nova', nova?.usar_agente === 1 ? 0 : 1)}
          >
            {nova?.usar_agente === 1 ? 'Desligar Agente na Nova' : 'Ligar Agente na Nova'}
          </button>
        </div>
      </section>
      {/* Tabela Comparativa dos 4 Cenários (Fatorial 2x2) */}
      <section className="secao-tabela">
        <h2>Resumo Comparativo dos 4 Cenários (Médias Consolidadas no PostgreSQL)</h2>
        <table className="tabela-metricas">
          <thead>
            <tr>
              <th>Arquitetura</th>
              <th>Cenário (Agente IA)</th>
              <th>Amostras</th>
              <th>CPU Média (%)</th>
              <th>CPU Pico (%)</th>
              <th>RAM Média (MB)</th>
              <th>Rede Média (KB/s)</th>
            </tr>
          </thead>
          <tbody>
            {(dados?.resumo_recursos || []).map((item: any, idx: number) => (
              <tr key={idx}>
                <td>{item.arquitetura}</td>
                <td>{Number(item.usar_agente) === 1 ? '🤖 Com Agente' : '⚡ Sem Agente'}</td>
                <td>{item.amostras}</td>
                <td>{item.cpu_media}%</td>
                <td>{item.cpu_pico}%</td>
                <td>{formatarTamanhoMB(Number(item.ram_media_mb))}</td>
                <td>{formatarVelocidadeKBps(Number(item.rede_media_kbps))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {/* Tabela Comparativa dos 4 Cenários (Latência e Alertas) */}
      <section className="secao-tabela">
        <h2>Resumo de Latência e Alertas (Presente Reativo vs. Futuro IA)</h2>
        <table className="tabela-metricas">
          <thead>
            <tr>
              <th>Arquitetura</th>
              <th>Cenário (Agente IA)</th>
              <th>Leituras</th>
              <th>Latência Total Média (ms)</th>
              <th>Latência IA Média (ms)</th>
              <th>Alertas Reativos</th>
              <th>Alertas Preditivos (+15m)</th>
            </tr>
          </thead>
          <tbody>
            {(dados?.resumo_leituras || []).map((item: any, idx: number) => (
              <tr key={idx}>
                <td>{item.arquitetura}</td>
                <td>{Number(item.usar_agente) === 1 ? '🤖 Com Agente' : '⚡ Sem Agente'}</td>
                <td>{item.total_leituras}</td>
                <td>{item.latencia_total_media_ms ?? '--'} ms</td>
                <td>{item.latencia_agente_media_ms ?? '--'} ms</td>
                <td>{item.alertas_reativos}</td>
                <td>{item.alertas_preditivos}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {/* Seletor de Janela de Tempo dos Gráficos */}
      <section className="barra-janela">
        <span>Janela dos Gráficos:</span>
        <div className="botoes-janela">
          {JANELAS.map((j) => (
            <button
              key={j.id}
              className={`btn-janela ${janela === j.id ? 'ativo' : ''}`}
              onClick={() => setJanela(j.id)}
            >
              {j.label}
            </button>
          ))}
        </div>
      </section>
      {/* Gráficos Comparativos Diretos: Velha vs. Nova (apenas quando ambas estão online) */}
      {velha?.online && nova?.online && (
        <section className="grid-graficos-comparativos">
          <div className="card-grafico">
            <h3>Comparativo CPU (%) — Velha vs. Nova</h3>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={dadosComparativos} margin={{ top: 12, right: 16, left: 4, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="timestamp" tickFormatter={(v) => formatarDataHora(v)} />
                <YAxis width={58} />
                <Tooltip
                  labelFormatter={(v) => formatarDataHora(v, true)}
                  formatter={(v: any, name: any) => [`${Number(v).toFixed(2)}%`, name]}
                />
                <Legend />
                <Line isAnimationActive={false} type="monotone" dataKey="cpu_velha" name="Arq. Velha" stroke="#ef4444" strokeWidth={2} dot={false} connectNulls />
                <Line isAnimationActive={false} type="monotone" dataKey="cpu_nova" name="Arq. Nova" stroke="#3b82f6" strokeWidth={2} dot={false} connectNulls />
                {renderMarcadores(marcadoresComparativos)}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="card-grafico">
            <h3>Comparativo Memória RAM — Velha vs. Nova</h3>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={dadosComparativos} margin={{ top: 12, right: 16, left: 4, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="timestamp" tickFormatter={(v) => formatarDataHora(v)} />
                <YAxis width={95} tickFormatter={(v) => formatarTamanhoMB(Number(v))} />
                <Tooltip
                  labelFormatter={(v) => formatarDataHora(v, true)}
                  formatter={(v: any, name: any) => [formatarTamanhoMB(Number(v)), name]}
                />
                <Legend />
                <Line isAnimationActive={false} type="monotone" dataKey="ram_velha" name="Arq. Velha" stroke="#a855f7" strokeWidth={2} dot={false} connectNulls />
                <Line isAnimationActive={false} type="monotone" dataKey="ram_nova" name="Arq. Nova" stroke="#06b6d4" strokeWidth={2} dot={false} connectNulls />
                {renderMarcadores(marcadoresComparativos)}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="card-grafico">
            <h3>Comparativo Rede RX — Velha vs. Nova</h3>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={dadosComparativos} margin={{ top: 12, right: 16, left: 4, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="timestamp" tickFormatter={(v) => formatarDataHora(v)} />
                <YAxis width={95} tickFormatter={(v) => formatarVelocidadeKBps(Number(v))} />
                <Tooltip
                  labelFormatter={(v) => formatarDataHora(v, true)}
                  formatter={(v: any, name: any) => [formatarVelocidadeKBps(Number(v)), name]}
                />
                <Legend />
                <Line isAnimationActive={false} type="monotone" dataKey="rede_velha" name="Arq. Velha" stroke="#f59e0b" strokeWidth={2} dot={false} connectNulls />
                <Line isAnimationActive={false} type="monotone" dataKey="rede_nova" name="Arq. Nova" stroke="#10b981" strokeWidth={2} dot={false} connectNulls />
                {renderMarcadores(marcadoresComparativos)}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
      {/* Gráficos em Tempo Real: Arquitetura Velha vs. Arquitetura Nova */}
      <section className="grid-graficos">
        <div className="card-grafico">
          <h3>Máquina 1 (Arquitetura Velha) — CPU (%) e Rede</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={histVelha} margin={{ top: 12, right: 16, left: 4, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={(v) => formatarDataHora(v)} />
              <YAxis width={68} />
              <Tooltip
                labelFormatter={(v) => formatarDataHora(v, true)}
                formatter={(v: any, name: any) =>
                  name === 'Rede RX'
                    ? [formatarVelocidadeKBps(Number(v)), name]
                    : [`${Number(v).toFixed(2)}%`, name]
                }
              />
              <Legend />
              <Line isAnimationActive={false} type="monotone" dataKey="cpu_percent" name="CPU (%)" stroke="#ef4444" strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} type="monotone" dataKey="net_rx_kbps" name="Rede RX" stroke="#f59e0b" strokeWidth={2} dot={false} />
              {renderMarcadores(marcadoresVelha)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card-grafico">
          <h3>Máquina 2 (Arquitetura Nova) — CPU (%) e Rede</h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={histNova} margin={{ top: 12, right: 16, left: 4, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={(v) => formatarDataHora(v)} />
              <YAxis width={68} />
              <Tooltip
                labelFormatter={(v) => formatarDataHora(v, true)}
                formatter={(v: any, name: any) =>
                  name === 'Rede RX'
                    ? [formatarVelocidadeKBps(Number(v)), name]
                    : [`${Number(v).toFixed(2)}%`, name]
                }
              />
              <Legend />
              <Line isAnimationActive={false} type="monotone" dataKey="cpu_percent" name="CPU (%)" stroke="#3b82f6" strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} type="monotone" dataKey="net_rx_kbps" name="Rede RX" stroke="#10b981" strokeWidth={2} dot={false} />
              {renderMarcadores(marcadoresNova)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card-grafico">
          <h3>Máquina 1 (Arquitetura Velha) — Memória RAM</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={histVelha} margin={{ top: 12, right: 16, left: 4, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={(v) => formatarDataHora(v)} />
              <YAxis width={95} tickFormatter={(v) => formatarTamanhoMB(Number(v))} />
              <Tooltip
                labelFormatter={(v) => formatarDataHora(v, true)}
                formatter={(v: any) => [formatarTamanhoMB(Number(v)), 'RAM']}
              />
              <Legend />
              <Line isAnimationActive={false} type="monotone" dataKey="mem_usage_mb" name="RAM" stroke="#a855f7" strokeWidth={2} dot={false} />
              {renderMarcadores(marcadoresVelha)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="card-grafico">
          <h3>Máquina 2 (Arquitetura Nova) — Memória RAM</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={histNova} margin={{ top: 12, right: 16, left: 4, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="timestamp" tickFormatter={(v) => formatarDataHora(v)} />
              <YAxis width={95} tickFormatter={(v) => formatarTamanhoMB(Number(v))} />
              <Tooltip
                labelFormatter={(v) => formatarDataHora(v, true)}
                formatter={(v: any) => [formatarTamanhoMB(Number(v)), 'RAM']}
              />
              <Legend />
              <Line isAnimationActive={false} type="monotone" dataKey="mem_usage_mb" name="RAM" stroke="#06b6d4" strokeWidth={2} dot={false} />
              {renderMarcadores(marcadoresNova)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>
      {/* Últimas Leituras: Latência (ms) e Comparativo Alerta Reativo vs. Agente IA (15 min à frente) */}
      <section className="secao-tabela">
        <h2>Últimas Leituras Processadas — Latência (ms) e Antecipação do Aviso (Presente vs. Futuro 15m)</h2>
        <table className="tabela-metricas">
          <thead>
            <tr>
              <th>Data / Hora</th>
              <th>Arquitetura</th>
              <th>Agente</th>
              <th>CO Atual</th>
              <th>IQAr Presente (Sem Agente)</th>
              <th>IQAr Previsto (+15m)</th>
              <th>CO Previsto (+15m)</th>
              <th>Alerta Agente IA</th>
              <th>Latência Total / IA (ms)</th>
            </tr>
          </thead>
          <tbody>
            {(dados?.ultimas_leituras || []).map((l: any, idx: number) => (
              <tr key={idx}>
                <td>{formatarDataHora(l.timestamp_recebimento, true)}</td>
                <td>{l.arquitetura}</td>
                <td>{Number(l.usar_agente) === 1 ? '🤖 Sim' : '⚡ Não'}</td>
                <td>{l.co_atual} ppm</td>
                <td>{l.iqar_reativo_presente}</td>
                <td><strong>{l.iqar_previsto_15m || '--'}</strong></td>
                <td>{l.co_previsto_15m ? `${l.co_previsto_15m} ppm` : '--'}</td>
                <td>{l.tipo_alerta_agente || 'Normal'}</td>
                <td>{l.latencia_total_ms} ms ({l.latencia_agente_ms} ms IA)</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
export default App