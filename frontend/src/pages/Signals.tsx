import { useEffect, useState } from 'react'
import { getSignals } from '../services/api'
import { Activity } from 'lucide-react'

export default function Signals() {
  const [signals, setSignals] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [limit, setLimit] = useState(12)

  const load = (n = limit) => {
    setLoading(true)
    getSignals(n)
      .then(r => setSignals(r.data || []))
      .catch(e => setError(e.response?.data?.detail || 'Failed to load signals'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const dirBadge = (d: string) =>
    d === 'bullish' ? 'badge-green' : d === 'bearish' ? 'badge-red' : 'badge-neutral'

  if (loading) return <div className="muted"><span className="live-dot" /> Loading AI signals…</div>
  if (error) return <div className="negative">{error}</div>

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>AI Signal Engine</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Trade ideas with thesis, confidence, risk score and invalidation. Research and paper-planning only.
          </p>
        </div>
        <div className="flex gap-8">
          <select
            value={limit}
            onChange={e => { const n = +e.target.value; setLimit(n); load(n) }}
            style={{ fontSize: 12 }}
          >
            <option value={6}>6 ideas</option>
            <option value={12}>12 ideas</option>
            <option value={20}>20 ideas</option>
          </select>
          <button className="btn btn-sm btn-primary" onClick={() => load()}>
            <Activity size={13} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid-12">
        {signals.map((s: any) => (
          <div key={s.id || s.asset + s.thesis} className={`signal-card col-6 ${s.direction}`}>
            <div className="flex-between mb-8">
              <div>
                <span className="mono" style={{ fontWeight: 600, fontSize: 14 }}>{s.asset}</span>
                <span className="badge badge-neutral" style={{ marginLeft: 8 }}>{s.asset_class}</span>
              </div>
              <div className="flex gap-8">
                <span className={`badge ${dirBadge(s.direction)}`}>{s.direction}</span>
                <span className="badge badge-blue">{s.confidence?.toFixed?.(0) ?? s.confidence}%</span>
              </div>
            </div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>
              {(s.signal_type || '').replace(/_/g, ' ')} · {s.time_horizon} · Risk {s.risk_score}/100
            </div>
            <div style={{ fontSize: 13, marginBottom: 8, lineHeight: 1.45 }}>{s.thesis}</div>
            {s.correlation_context && (
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                <strong>Cross-asset:</strong> {s.correlation_context}
              </div>
            )}
            {s.macro_context && (
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                <strong>Macro:</strong> {s.macro_context}
              </div>
            )}
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
              <strong>Invalidation:</strong> {s.invalidation}
            </div>
            {s.paper_trade_setup && (
              <div className="muted" style={{ fontSize: 11 }}>
                <strong>Paper setup:</strong> {s.paper_trade_setup}
              </div>
            )}
            <div className="muted" style={{ fontSize: 10, marginTop: 8 }}>
              {s.disclaimer || 'Research only, not financial advice.'}
            </div>
          </div>
        ))}
      </div>

      {signals.length === 0 && (
        <div className="panel muted">No signals returned. Check API health or try refresh.</div>
      )}

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        AI-assisted research only. Not financial advice. Does not guarantee profits. Paper-trade planning only in Phase 1.
      </p>
    </div>
  )
}
