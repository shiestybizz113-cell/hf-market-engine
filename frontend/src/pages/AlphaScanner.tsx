import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getSignals, getCorrelations } from '../services/api'
import { Crosshair, Activity } from 'lucide-react'

const alphaScore = (s: any) =>
  Math.round((s.confidence || 0) * (1 - (s.risk_score || 0) / 100))

export default function AlphaScanner() {
  const navigate = useNavigate()
  const [signals, setSignals] = useState<any[]>([])
  const [corrs, setCorrs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [classFilter, setClassFilter] = useState('all')
  const [dirFilter, setDirFilter] = useState('all')

  const load = () => {
    setLoading(true)
    Promise.all([
      getSignals(20).then(r => setSignals(r.data || [])).catch(e => setError(e.response?.data?.detail || 'Failed to load ideas')),
      getCorrelations().then(r => setCorrs(r.data || [])).catch(() => {}),
    ]).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const rows = useMemo(() => {
    let out = [...signals]
    if (classFilter !== 'all') out = out.filter(s => s.asset_class === classFilter)
    if (dirFilter !== 'all') out = out.filter(s => s.direction === dirFilter)
    return out.sort((a, b) => alphaScore(b) - alphaScore(a))
  }, [signals, classFilter, dirFilter])

  const classes = useMemo(() => {
    const seen = new Set<string>()
    signals.forEach(s => seen.add(s.asset_class))
    return ['all', ...Array.from(seen)]
  }, [signals])

  const stats = useMemo(() => {
    const bullish = signals.filter(s => s.direction === 'bullish').length
    const bearish = signals.filter(s => s.direction === 'bearish').length
    const avgConf = signals.length ? signals.reduce((a, s) => a + (s.confidence || 0), 0) / signals.length : 0
    const top = signals.length ? signals.reduce((a, b) => (alphaScore(a) > alphaScore(b) ? a : b)) : null
    return { bullish, bearish, avgConf, top }
  }, [signals])

  const dirBadge = (d: string) =>
    d === 'bullish' ? 'badge-green' : d === 'bearish' ? 'badge-red' : 'badge-neutral'

  if (loading) return <div className="muted"><span className="live-dot" /> Scanning signals…</div>
  if (error && signals.length === 0) return <div className="negative">{error}</div>

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>Alpha Scanner</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Ranks AI trade ideas by alpha score = confidence × (1 − risk/100). Research & simulation only.
          </p>
        </div>
        <button className="btn btn-sm btn-primary" onClick={load}>
          <Activity size={13} /> Rescan
        </button>
      </div>

      <div className="grid-12 mb-8">
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Ideas</span></div>
          <div className="mono" style={{ fontSize: 22 }}>{signals.length}</div>
        </div>
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Bullish</span></div>
          <div className="mono positive" style={{ fontSize: 22 }}>{stats.bullish}</div>
        </div>
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Bearish</span></div>
          <div className="mono negative" style={{ fontSize: 22 }}>{stats.bearish}</div>
        </div>
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Avg Confidence</span></div>
          <div className="mono" style={{ fontSize: 22 }}>{stats.avgConf.toFixed(0)}%</div>
        </div>
      </div>

      <div className="flex gap-8 mb-8" style={{ alignItems: 'center' }}>
        <Crosshair size={14} className="muted" />
        <select value={classFilter} onChange={e => setClassFilter(e.target.value)} style={{ fontSize: 12 }}>
          {classes.map(c => (
            <option key={c} value={c}>{c === 'all' ? 'All classes' : c}</option>
          ))}
        </select>
        <select value={dirFilter} onChange={e => setDirFilter(e.target.value)} style={{ fontSize: 12 }}>
          <option value="all">All directions</option>
          <option value="bullish">Bullish</option>
          <option value="bearish">Bearish</option>
        </select>
      </div>

      <div className="panel mb-8">
        <div className="panel-header">
          <span className="panel-title">Ranked Ideas</span>
          <span className="badge badge-blue">Alpha score ↓</span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>#</th><th>Asset</th><th>Class</th><th>Direction</th><th>Signal</th>
              <th>Horizon</th><th className="text-right">Conf.</th><th className="text-right">Risk</th>
              <th className="text-right">Alpha</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s: any, i: number) => (
              <tr key={s.id || s.asset + s.thesis} style={{ cursor: 'pointer' }} onClick={() => navigate(`/asset/${s.asset}?class=${s.asset_class}`)}>
                <td className="muted">{i + 1}</td>
                <td className="mono" style={{ fontWeight: 600 }}>{s.asset}</td>
                <td><span className="badge badge-neutral">{s.asset_class}</span></td>
                <td><span className={`badge ${dirBadge(s.direction)}`}>{s.direction}</span></td>
                <td className="muted" style={{ fontSize: 11 }}>{s.signal_type?.replace(/_/g, ' ')}</td>
                <td className="muted" style={{ fontSize: 11 }}>{s.time_horizon}</td>
                <td className="text-right mono">{s.confidence?.toFixed(0)}%</td>
                <td className="text-right mono">{s.risk_score?.toFixed(0)}/100</td>
                <td className="text-right mono" style={{ fontWeight: 700 }}>{alphaScore(s)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={9} className="muted">No ideas match the current filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {stats.top && (
        <div className="signal-card col-12 bullish mb-8">
          <div className="flex-between mb-8">
            <div>
              <span className="mono" style={{ fontWeight: 600, fontSize: 14 }}>{stats.top.asset}</span>
              <span className="badge badge-neutral" style={{ marginLeft: 8 }}>{stats.top.asset_class}</span>
              <span className={`badge ${dirBadge(stats.top.direction)}`} style={{ marginLeft: 8 }}>{stats.top.direction}</span>
            </div>
            <span className="badge badge-blue">Top idea · alpha {alphaScore(stats.top)}</span>
          </div>
          <div style={{ fontSize: 13, marginBottom: 6 }}>{stats.top.thesis}</div>
          <div className="muted" style={{ fontSize: 11 }}>
            <strong>Invalidation:</strong> {stats.top.invalidation}
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-header"><span className="panel-title">Correlation Context</span></div>
        <div className="grid-12">
          {(corrs || []).map((c: any) => (
            <div key={c.pair} className="col-6" style={{ marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid var(--border)' }}>
              <div className="flex-between">
                <span className="mono" style={{ fontWeight: 600 }}>{c.pair}</span>
                <span className={`badge ${c.status === 'Diverging' ? 'badge-amber' : 'badge-neutral'}`}>{c.status}</span>
              </div>
              <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                ρ = {c.correlation?.toFixed(2)} · {c.relationship_type}
              </div>
            </div>
          ))}
        </div>
      </div>

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        AI-assisted research only. Not financial advice. Does not guarantee profits.
      </p>
    </div>
  )
}
