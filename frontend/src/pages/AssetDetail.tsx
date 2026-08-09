import { useEffect, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getAsset } from '../services/api'

export default function AssetDetail() {
  const { symbol } = useParams()
  const [params] = useSearchParams()
  const assetClass = params.get('class') || 'crypto'
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!symbol) return
    setLoading(true)
    getAsset(symbol, assetClass)
      .then(r => setData(r.data))
      .catch(e => setError(e.response?.data?.detail || 'Asset not found'))
      .finally(() => setLoading(false))
  }, [symbol, assetClass])

  const fmt = (n?: number, d = 2) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: d }) : '—'
  const pct = (n?: number) => n != null ? (
    <span className={n >= 0 ? 'positive mono' : 'negative mono'}>{n >= 0 ? '+' : ''}{n.toFixed(2)}%</span>
  ) : '—'

  if (loading) return <div className="muted">Loading {symbol}…</div>
  if (error) return <div className="negative">{error}</div>
  if (!data) return null

  const q = data.quote
  const signal = data.latest_signal

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 22 }} className="mono">{q.symbol}</h2>
          <div className="muted">{q.name} · <span className="badge badge-neutral">{q.asset_class}</span></div>
        </div>
        <div className="text-right">
          <div className="mono" style={{ fontSize: 26, fontWeight: 600 }}>${fmt(q.price, q.price < 1 ? 4 : 2)}</div>
          <div>{pct(q.change_24h)} <span className="muted">24h</span></div>
        </div>
      </div>

      <div className="grid-12">
        <div className="panel col-8">
          <div className="panel-header"><span className="panel-title">Market Data</span></div>
          <div className="grid-12">
            {[
              { l: 'Market Cap', v: q.market_cap ? '$' + (q.market_cap / 1e9).toFixed(2) + 'B' : '—' },
              { l: '24h Volume', v: q.volume_24h ? '$' + (q.volume_24h / 1e6).toFixed(1) + 'M' : '—' },
              { l: '24h High', v: q.high_24h ? '$' + fmt(q.high_24h) : '—' },
              { l: '24h Low', v: q.low_24h ? '$' + fmt(q.low_24h) : '—' },
              { l: '7d Change', v: pct(q.change_7d) },
              { l: '30d Change', v: pct(q.change_30d) },
              { l: 'Source', v: q.source },
              { l: 'Updated', v: q.last_updated ? new Date(q.last_updated).toLocaleTimeString() : '—' },
            ].map(m => (
              <div key={m.l} className="col-3" style={{ marginBottom: 10 }}>
                <div className="muted" style={{ fontSize: 10 }}>{m.l}</div>
                <div className="mono" style={{ fontSize: 14 }}>{m.v}</div>
              </div>
            ))}
          </div>
          <div className="muted mt-8" style={{ fontSize: 11 }}>
            Chart placeholder — Phase 1 uses live quotes. Full candle charts arrive with historical bar provider.
          </div>
        </div>

        <div className="panel col-4">
          <div className="panel-header">
            <span className="panel-title">AI Market Summary</span>
            <span className="badge badge-amber">Research</span>
          </div>
          <p style={{ fontSize: 13, lineHeight: 1.5, marginBottom: 12 }}>{data.ai_summary}</p>
          {signal && (
            <div className={`signal-card ${signal.direction}`} style={{ margin: 0 }}>
              <div className="flex-between mb-8">
                <span className={`badge ${signal.direction === 'bullish' ? 'badge-green' : signal.direction === 'bearish' ? 'badge-red' : 'badge-neutral'}`}>
                  {signal.direction}
                </span>
                <span className="badge badge-blue">{signal.confidence?.toFixed(0)}%</span>
              </div>
              <div className="muted" style={{ fontSize: 11 }}>{signal.signal_type?.replace(/_/g, ' ')} · {signal.time_horizon}</div>
              <div style={{ fontSize: 12, marginTop: 6 }}>Risk {signal.risk_score}/100</div>
              <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
                <strong>Invalidation:</strong> {signal.invalidation}
              </div>
            </div>
          )}
          <button className="btn btn-primary mt-12" style={{ width: '100%' }}>
            Add to Paper-Trade Watchlist
          </button>
        </div>
      </div>

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        {data.disclaimer || 'Research only, not financial advice. Does not guarantee profits.'}
      </p>
    </div>
  )
}
