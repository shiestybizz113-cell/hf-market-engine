import { useEffect, useState } from 'react'
import { getCorrelations } from '../services/api'
import { GitBranch } from 'lucide-react'

export default function Correlations() {
  const [pairs, setPairs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getCorrelations()
      .then(r => setPairs(r.data || []))
      .catch(e => setError(e.response?.data?.detail || 'Failed to load correlations'))
      .finally(() => setLoading(false))
  }, [])

  const statusBadge = (s: string) => {
    if (s === 'Diverging') return 'badge-amber'
    if (s === 'Aligned') return 'badge-green'
    return 'badge-neutral'
  }

  const corrColor = (c: number) => {
    if (c >= 0.6) return 'positive'
    if (c <= -0.4) return 'negative'
    return ''
  }

  if (loading) return <div className="muted"><span className="live-dot" /> Loading correlation radar…</div>
  if (error) return <div className="negative">{error}</div>

  return (
    <div>
      <div className="mb-8">
        <h2 style={{ fontSize: 18 }}>Correlation Radar</h2>
        <p className="muted" style={{ fontSize: 12 }}>
          Cross-asset relationships for research. Divergence and alignment are signals to investigate — not trade instructions.
        </p>
      </div>

      <div className="grid-12">
        {pairs.map((p: any) => (
          <div key={p.pair} className="panel col-6">
            <div className="panel-header">
              <span className="panel-title mono flex gap-8" style={{ alignItems: 'center' }}>
                <GitBranch size={14} /> {p.pair}
              </span>
              <span className={`badge ${statusBadge(p.status)}`}>{p.status}</span>
            </div>
            <div className="flex-between mb-8">
              <div>
                <div className="muted" style={{ fontSize: 10 }}>Correlation (ρ)</div>
                <div className={`mono ${corrColor(p.correlation)}`} style={{ fontSize: 22, fontWeight: 600 }}>
                  {p.correlation?.toFixed(2)}
                </div>
              </div>
              <div className="text-right">
                <div className="muted" style={{ fontSize: 10 }}>Relationship</div>
                <div style={{ fontSize: 12 }}>{p.relationship_type}</div>
              </div>
            </div>
            <p style={{ fontSize: 12, lineHeight: 1.5, marginBottom: 8 }}>{p.ai_explanation}</p>
            {p.risk_warning && (
              <div className="panel" style={{ background: 'var(--bg)', borderColor: 'var(--amber)', marginTop: 8 }}>
                <div className="amber" style={{ fontSize: 11, fontWeight: 600 }}>Risk note</div>
                <p style={{ fontSize: 11 }}>{p.risk_warning}</p>
              </div>
            )}
          </div>
        ))}
      </div>

      {pairs.length === 0 && (
        <div className="panel muted">No correlation pairs returned. Check market API / health.</div>
      )}

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Research only. Correlations shift; they are not guarantees. Not financial advice.
      </p>
    </div>
  )
}
