import { useEffect, useState } from 'react'
import { getHealth } from '../services/api'
import { Activity, Database, Wifi, Brain, Shield, Users, FlaskConical, FileText } from 'lucide-react'

export default function SystemHealth() {
  const [health, setHealth] = useState<any>(null)
  const [error, setError] = useState('')
  const [ts, setTs] = useState<Date | null>(null)

  const load = () => {
    getHealth()
      .then(r => { setHealth(r.data); setTs(new Date()); setError('') })
      .catch(e => setError(e.message || 'Health check failed'))
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const statusColor = (s?: string) => {
    if (!s) return 'badge-neutral'
    if (s === 'ok' || s === 'operational') return 'badge-green'
    if (s === 'degraded' || s === 'template') return 'badge-amber'
    return 'badge-red'
  }

  const Row = ({ icon: Icon, label, value }: any) => (
    <div className="flex-between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
      <div className="flex gap-8" style={{ alignItems: 'center' }}>
        <Icon size={14} className="muted" />
        <span>{label}</span>
      </div>
      <span className={`badge ${statusColor(value)}`}>{value || '—'}</span>
    </div>
  )

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>System Health</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Live status of API, database, market data, AI and auth layers.
            {ts && <> · Last refresh {ts.toLocaleTimeString()}</>}
          </p>
        </div>
        <button className="btn btn-sm" onClick={load}>Refresh</button>
      </div>

      {error && <div className="negative mb-8">{error}</div>}

      {!health ? (
        <div className="muted">Loading health…</div>
      ) : (
        <div className="grid-12">
          <div className="panel col-6">
            <div className="panel-header">
              <span className="panel-title">Core Services</span>
              <span className={`badge ${statusColor(health.status)}`}>{health.status}</span>
            </div>
            <Row icon={Activity} label="API" value={health.api} />
            <Row icon={Database} label="Database" value={health.database} />
            <Row icon={Wifi} label="CoinGecko" value={health.coingecko} />
            <Row icon={Brain} label="AI Layer" value={health.ai} />
            <Row icon={Shield} label="Auth" value={health.auth} />
          </div>

          <div className="panel col-6">
            <div className="panel-header"><span className="panel-title">Usage Snapshot</span></div>
            <div className="flex-between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div className="flex gap-8" style={{ alignItems: 'center' }}>
                <Users size={14} className="muted" />
                <span>Registered users</span>
              </div>
              <span className="mono">{health.active_users ?? 0}</span>
            </div>
            <div className="flex-between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div className="flex gap-8" style={{ alignItems: 'center' }}>
                <FlaskConical size={14} className="muted" />
                <span>Saved strategies</span>
              </div>
              <span className="mono">{health.saved_strategies ?? 0}</span>
            </div>
            <div className="flex-between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div className="flex gap-8" style={{ alignItems: 'center' }}>
                <FileText size={14} className="muted" />
                <span>Paper trades</span>
              </div>
              <span className="mono">{health.paper_trades ?? 0}</span>
            </div>
            <div className="flex-between" style={{ padding: '10px 0' }}>
              <span className="muted">Last market refresh</span>
              <span className="mono" style={{ fontSize: 11 }}>
                {health.last_market_refresh
                  ? new Date(health.last_market_refresh).toLocaleString()
                  : '—'}
              </span>
            </div>
          </div>

          <div className="panel col-12" style={{ borderColor: 'var(--amber)' }}>
            <div className="panel-header"><span className="panel-title">Phase Status</span></div>
            <div className="grid-12" style={{ fontSize: 12 }}>
              <div className="col-4">
                <strong className="positive">Phase 1 Live</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>Research & signals</li>
                  <li>Paper trading</li>
                  <li>Execution simulation</li>
                  <li>Risk engine</li>
                  <li>Journal auto-entry</li>
                </ul>
              </div>
              <div className="col-4">
                <strong className="amber">Phase 2 Ready</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>Execution engine interface</li>
                  <li>Parent/child order models</li>
                  <li>Algo catalog + recommend</li>
                  <li>Live connector slots</li>
                </ul>
              </div>
              <div className="col-4">
                <strong className="muted">Not enabled</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>Real exchange execution</li>
                  <li>Live SOR / CCXT</li>
                  <li>Stripe billing</li>
                  <li>White-label runtime</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
