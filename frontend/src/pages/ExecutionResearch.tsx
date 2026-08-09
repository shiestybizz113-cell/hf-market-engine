import { useEffect, useState } from 'react'
import api from '../services/api'
import { Clock, BarChart2, Percent, Target, Eye, Cpu, GitBranch, Shield } from 'lucide-react'

const ICONS: Record<string, any> = {
  twap: Clock,
  vwap: BarChart2,
  pov: Percent,
  implementation_shortfall: Target,
  iceberg: Eye,
  adaptive: Cpu,
  smart_order_router: GitBranch,
  market: Target,
}

export default function ExecutionResearch() {
  const [algos, setAlgos] = useState<any[]>([])
  const [active, setActive] = useState<string>('twap')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/execution/algos')
      .then(r => {
        setAlgos(r.data)
        if (r.data.length) setActive(r.data[0].algo_type)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const algo = algos.find(a => a.algo_type === active)

  if (loading) return <div className="muted">Loading execution strategies…</div>

  return (
    <div>
      <div className="mb-8">
        <h2 style={{ fontSize: 18 }}>Algorithmic Execution Strategies</h2>
        <p className="muted" style={{ fontSize: 12 }}>
          Research panel — how institutions slice large orders to control impact, timing risk and information leakage.
          Phase 1 is educational + paper simulation only. Live venue routing arrives in Phase 2.
        </p>
      </div>

      <div className="flex gap-8 mb-8" style={{ flexWrap: 'wrap' }}>
        {algos.map(a => {
          const Icon = ICONS[a.algo_type] || Target
          return (
            <button
              key={a.algo_type}
              className={`btn btn-sm ${active === a.algo_type ? 'btn-primary' : ''}`}
              onClick={() => setActive(a.algo_type)}
            >
              <Icon size={13} /> {a.name.split('—')[0].trim()}
            </button>
          )
        })}
      </div>

      {algo && (
        <div className="grid-12">
          <div className="panel col-8">
            <div className="panel-header">
              <span className="panel-title">{algo.name}</span>
              <span className="badge badge-amber">Research</span>
            </div>
            <p style={{ fontSize: 13, lineHeight: 1.55, marginBottom: 14 }}>{algo.short_description}</p>

            <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>
              How it works
            </div>
            <p style={{ fontSize: 12, lineHeight: 1.5, marginBottom: 14 }}>{algo.how_it_works}</p>

            <div className="grid-12">
              <div className="col-6">
                <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>Best for</div>
                <ul style={{ paddingLeft: 16, fontSize: 12 }}>
                  {algo.best_for?.map((b: string, i: number) => <li key={i} style={{ marginBottom: 3 }}>{b}</li>)}
                </ul>
              </div>
              <div className="col-6">
                <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>Weaknesses</div>
                <ul style={{ paddingLeft: 16, fontSize: 12 }}>
                  {algo.weaknesses?.map((w: string, i: number) => <li key={i} style={{ marginBottom: 3 }}>{w}</li>)}
                </ul>
              </div>
            </div>

            <div className="panel mt-12" style={{ background: 'var(--bg)', borderColor: 'var(--accent)' }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--accent)', marginBottom: 4 }}>Crypto-specific notes</div>
              <p style={{ fontSize: 12 }}>{algo.crypto_notes}</p>
            </div>
          </div>

          <div className="panel col-4">
            <div className="panel-header"><span className="panel-title">Typical Parameters</span></div>
            <table className="table">
              <tbody>
                {Object.entries(algo.typical_params || {}).map(([k, v]) => (
                  <tr key={k}>
                    <td className="muted" style={{ fontSize: 11 }}>{k.replace(/_/g, ' ')}</td>
                    <td className="mono text-right">{String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div className="mt-12">
              <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>Selection heuristic</div>
              <div style={{ fontSize: 11, lineHeight: 1.5, color: 'var(--text-secondary)' }}>
                <div>• High urgency + small size → cross / aggressive</div>
                <div>• Low urgency + large size → TWAP or Iceberg</div>
                <div>• Benchmark-sensitive → VWAP (equities) / calibrated TWAP (crypto)</div>
                <div>• Uncertain volume → POV</div>
                <div>• Fragmented liquidity → SOR under any parent algo</div>
              </div>
            </div>
          </div>

          <div className="panel col-12" style={{ borderColor: 'var(--amber)' }}>
            <div className="panel-header">
              <span className="panel-title flex gap-8" style={{ alignItems: 'center' }}>
                <Shield size={14} /> Phase 2 Execution Engine Readiness
              </span>
              <span className="badge badge-amber">Architecture Ready</span>
            </div>
            <div className="grid-12" style={{ fontSize: 12 }}>
              <div className="col-4">
                <strong>Already built</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>Parent / Child order models</li>
                  <li>Algo config + catalog</li>
                  <li>PaperExecutionEngine (sim fills)</li>
                  <li>Risk Engine as mandatory gate</li>
                  <li>Analytics (shortfall, fees, venues)</li>
                  <li>Recommend-algo heuristic</li>
                </ul>
              </div>
              <div className="col-4">
                <strong>Phase 2 plug-ins</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>CCXT / exchange REST+WS connectors</li>
                  <li>Smart Order Router across CEXs</li>
                  <li>Pre-funding & balance checks</li>
                  <li>Live participation & book monitors</li>
                  <li>Kill-switch + daily loss hard stops</li>
                  <li>Human approval mode (optional)</li>
                </ul>
              </div>
              <div className="col-4">
                <strong>Safety invariants</strong>
                <ul style={{ paddingLeft: 16, marginTop: 4 }}>
                  <li>paper_mode default = true</li>
                  <li>Risk Engine non-bypassable</li>
                  <li>Max participation hard caps</li>
                  <li>Fail-closed on data loss</li>
                  <li>Full audit trail of child orders</li>
                  <li>Explicit live enablement flag</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Educational content only. hf-market-engine does not execute real orders in Phase 1.
        Trading involves substantial risk. Not financial advice.
      </p>
    </div>
  )
}
