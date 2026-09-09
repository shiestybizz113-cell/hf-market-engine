import { useEffect, useState } from 'react'
import { getHealth } from '../services/api'
import { Activity, Brain, Database, FileText, Gauge, Shield, Wifi } from 'lucide-react'

export default function SystemHealth() {
  const [health, setHealth] = useState<any>(null)
  const [error, setError] = useState('')
  const [ts, setTs] = useState<Date | null>(null)

  const load = () => {
    getHealth()
      .then(r => { setHealth(r.data); setTs(new Date()); setError('') })
      .catch(e => setError(e.response?.data?.detail || e.message || 'Health check failed'))
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const statusColor = (s?: string) => {
    if (!s) return 'badge-neutral'
    if (s === 'ok' || s === 'operational') return 'badge-green'
    if (s === 'demo' || s === 'degraded' || s === 'template') return 'badge-amber'
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
            Authenticated operator status for the Capital + Compute runtime.
            {ts && <> · Last refresh {ts.toLocaleTimeString()}</>}
          </p>
        </div>
        <button className="btn btn-sm" onClick={load}>Refresh</button>
      </div>

      {error && <div className="negative mb-8">{String(error)}</div>}

      {!health ? <div className="muted">Loading health…</div> : (
        <div className="grid-12">
          <div className="panel col-6">
            <div className="panel-header">
              <span className="panel-title">Core Services</span>
              <span className={`badge ${statusColor(health.status)}`}>{health.status}</span>
            </div>
            <Row icon={Activity} label="API" value={health.api} />
            <Row icon={Database} label="Database" value={health.database} />
            <Row icon={Wifi} label={`Market data (${health.market_data_mode || 'unknown'})`} value={health.coingecko} />
            <Row icon={Brain} label="AI Layer" value={health.ai} />
            <Row icon={Shield} label="Auth" value={health.auth} />
          </div>

          <div className="panel col-6">
            <div className="panel-header"><span className="panel-title">Your Workspace</span></div>
            <div className="flex-between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div className="flex gap-8" style={{ alignItems: 'center' }}><Gauge size={14} className="muted" /><span>Market mode</span></div>
              <span className="mono">{health.market_data_mode || '—'}</span>
            </div>
            <div className="flex-between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div className="flex gap-8" style={{ alignItems: 'center' }}><FileText size={14} className="muted" /><span>Your saved strategies</span></div>
              <span className="mono">{health.saved_strategies ?? 0}</span>
            </div>
            <div className="flex-between" style={{ padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div className="flex gap-8" style={{ alignItems: 'center' }}><FileText size={14} className="muted" /><span>Your paper trades</span></div>
              <span className="mono">{health.paper_trades ?? 0}</span>
            </div>
            <div className="flex-between" style={{ padding: '10px 0' }}>
              <span className="muted">Health observed</span>
              <span className="mono" style={{ fontSize: 11 }}>{health.last_market_refresh ? new Date(health.last_market_refresh).toLocaleString() : '—'}</span>
            </div>
          </div>

          <div className="panel col-12" style={{ borderColor: 'var(--accent)' }}>
            <div className="panel-header"><span className="panel-title">Capital Command Center V2 Runtime</span><span className="badge badge-blue">PUBLIC BUILD</span></div>
            <div className="grid-12" style={{ fontSize: 12 }}>
              <div className="col-4">
                <strong className="positive">Operating now</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>Capital allocation + stress scenarios</li>
                  <li>Mining + GPU + energy economics</li>
                  <li>Immutable evidence receipts</li>
                  <li>Proof graph + provider freshness</li>
                </ul>
              </div>
              <div className="col-4">
                <strong className="positive">Scale controls</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>Mongo-backed shared state</li>
                  <li>Redis rate limits + provider refresh gates</li>
                  <li>Request IDs + readiness checks</li>
                  <li>Multi-worker production runtime</li>
                </ul>
              </div>
              <div className="col-4">
                <strong className="amber">Explicit boundaries</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>Optimizer proposes only</li>
                  <li>No Capital trade/spend/deploy action</li>
                  <li>Missing live data stays missing</li>
                  <li>Reference inputs remain assumptions</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
