import { useEffect, useState } from 'react'
import { getOverview, getMovers, getSignals, getCorrelations } from '../services/api'
import EvidenceStamp from '../components/EvidenceStamp'

export default function Dashboard() {
  const [overview, setOverview] = useState<any>(null)
  const [movers, setMovers] = useState<any>({ gainers: [], losers: [] })
  const [signals, setSignals] = useState<any[]>([])
  const [corrs, setCorrs] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getOverview().then(r => setOverview(r.data)).catch(() => {}),
      getMovers('crypto').then(r => setMovers(r.data)).catch(() => {}),
      getSignals(6).then(r => setSignals(r.data)).catch(() => {}),
      getCorrelations().then(r => setCorrs(r.data)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  const fmt = (n?: number, d = 2) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: d }) : '—'
  const pct = (n?: number) => n != null ? (
    <span className={n >= 0 ? 'positive mono' : 'negative mono'}>
      {n >= 0 ? '+' : ''}{n.toFixed(2)}%
    </span>
  ) : '—'

  if (loading) return (
    <div className="muted" style={{ padding: 40, textAlign: 'center' }}>
      Loading market data…
    </div>
  )

  return (
    <div className="grid-12">
      {/* Market Overview */}
      <div className="panel col-12">
        <div className="panel-header">
          <span className="panel-title">Market Overview</span>
          <span className="badge badge-amber">
            {overview?.regime?.replace(/-/g, ' ') || '—'} ({overview?.regime_confidence?.toFixed(0) || '—'}%)
          </span>
        </div>
        <div className="flex gap-12" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ minWidth: 220 }}>
            <div className="hero-label">BTC / USD</div>
            <div className="hero-readout"><span className="hero-unit">$</span>{fmt(overview?.btc?.price)}</div>
            <div className="flex gap-8" style={{ marginTop: 6 }}>
              {pct(overview?.btc?.change_24h)}
              <EvidenceStamp source={overview?.btc?.source} provider={overview?.btc?.provider} observedAt={overview?.btc?.observed_at} />
            </div>
          </div>
          <div style={{ borderLeft: '1px solid var(--border)', paddingLeft: 20, marginLeft: 4 }}>
            <div className="muted" style={{ fontSize: 11 }}>ETH</div>
            <div className="mono" style={{ fontSize: 18 }}>${fmt(overview?.eth?.price)}</div>
            <div>{pct(overview?.eth?.change_24h)}</div>
            <EvidenceStamp source={overview?.eth?.source} provider={overview?.eth?.provider} observedAt={overview?.eth?.observed_at} />
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11 }}>Market Cap</div>
            <div className="mono" style={{ fontSize: 16 }}>
              ${overview?.total_market_cap ? (overview.total_market_cap / 1e12).toFixed(2) + 'T' : '—'}
            </div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11 }}>24h Volume</div>
            <div className="mono" style={{ fontSize: 16 }}>
              ${overview?.total_volume_24h ? (overview.total_volume_24h / 1e9).toFixed(1) + 'B' : '—'}
            </div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11 }}>BTC Dom</div>
            <div className="mono" style={{ fontSize: 16 }}>
              {overview?.btc_dominance ? overview.btc_dominance.toFixed(1) + '%' : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* Movers */}
      <div className="panel col-4">
        <div className="panel-header">
          <span className="panel-title">Top Gainers</span>
        </div>
        <table className="table">
          <thead><tr><th>Asset</th><th className="text-right">Price</th><th className="text-right">24h</th></tr></thead>
          <tbody>
            {(movers.gainers || []).slice(0, 6).map((m: any) => (
              <tr key={m.symbol}>
                <td className="mono">{m.symbol}</td>
                <td className="text-right mono">${fmt(m.price)}</td>
                <td className="text-right">{pct(m.change_24h)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel col-4">
        <div className="panel-header">
          <span className="panel-title">Top Losers</span>
        </div>
        <table className="table">
          <thead><tr><th>Asset</th><th className="text-right">Price</th><th className="text-right">24h</th></tr></thead>
          <tbody>
            {(movers.losers || []).slice(0, 6).map((m: any) => (
              <tr key={m.symbol}>
                <td className="mono">{m.symbol}</td>
                <td className="text-right mono">${fmt(m.price)}</td>
                <td className="text-right">{pct(m.change_24h)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Correlation Radar snapshot */}
      <div className="panel col-4">
        <div className="panel-header">
          <span className="panel-title">Correlation Radar</span>
        </div>
        {(corrs || []).slice(0, 4).map((c: any) => (
          <div key={c.pair} style={{ marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid var(--border)' }}>
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

      {/* AI Signals */}
      <div className="panel col-12">
        <div className="panel-header">
          <span className="panel-title">AI Signal Engine</span>
          <span className="badge badge-blue">Research Only</span>
        </div>
        <div className="grid-12">
          {signals.map((s: any) => (
            <div key={s.id} className={`signal-card col-6 ${s.direction}`}>
              <div className="flex-between mb-8">
                <div>
                  <span className="mono" style={{ fontWeight: 600, fontSize: 14 }}>{s.asset}</span>
                  <span className="badge badge-neutral" style={{ marginLeft: 8 }}>{s.asset_class}</span>
                </div>
                <div className="flex gap-8">
                  <span className={`badge ${s.direction === 'bullish' ? 'badge-green' : s.direction === 'bearish' ? 'badge-red' : 'badge-neutral'}`}>
                    {s.direction}
                  </span>
                  <span className="badge badge-blue">{s.confidence?.toFixed(0)}%</span>
                </div>
              </div>
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                {s.signal_type?.replace(/_/g, ' ')} · {s.time_horizon} · Risk {s.risk_score?.toFixed(0)}/100
              </div>
              <div style={{ fontSize: 12, marginBottom: 6 }}>{s.thesis}</div>
              <div className="muted" style={{ fontSize: 11 }}>
                <strong>Invalidation:</strong> {s.invalidation}
              </div>
              <div className="muted" style={{ fontSize: 10, marginTop: 6 }}>{s.disclaimer}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
