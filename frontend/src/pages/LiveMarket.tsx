import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getOverview, getMovers, getPrices } from '../services/api'

const CONFIG: Record<string, { title: string; subtitle: string; symbols: string; units: string }> = {
  crypto: {
    title: 'Crypto Markets',
    subtitle: 'Live quotes via CoinGecko with demo fallback.',
    symbols: 'BTC,ETH,SOL,LINK,AVAX,DOGE,XRP,ADA,DOT,MATIC',
    units: '$',
  },
  stock: {
    title: 'Stocks',
    subtitle: 'Demo feed — abstraction ready for Polygon / Alpaca / Finnhub.',
    symbols: 'COIN,MSTR,NVDA,AAPL,MSFT,TSLA,AMZN',
    units: '$',
  },
  etf: {
    title: 'ETFs',
    subtitle: 'Demo feed for broad market, growth, small-cap, gold and treasuries.',
    symbols: 'SPY,QQQ,IWM,GLD,TLT',
    units: '$',
  },
  macro: {
    title: 'Macro / Forex',
    subtitle: 'Dollar index, gold and the 10-year yield as regime inputs.',
    symbols: 'DXY,XAUUSD,US10Y',
    units: '',
  },
}

export default function LiveMarket({ market }: { market: string }) {
  const cfg = CONFIG[market] || CONFIG.crypto
  const navigate = useNavigate()
  const [quotes, setQuotes] = useState<any[]>([])
  const [movers, setMovers] = useState<any>({ gainers: [], losers: [] })
  const [overview, setOverview] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  const load = (silent = false) => {
    if (!silent) setLoading(true)
    else setRefreshing(true)
    const promises = [
      getMovers(market).then(r => setMovers(r.data)).catch(() => {}),
      getPrices(cfg.symbols, market).then(r => setQuotes(r.data || [])).catch(e => setError(e.response?.data?.detail || 'Failed to load quotes')),
    ]
    if (market === 'crypto') {
      promises.push(getOverview().then(r => setOverview(r.data)).catch(() => {}))
    }
    Promise.all(promises).finally(() => { setLoading(false); setRefreshing(false) })
  }

  useEffect(() => { load() }, [market])

  const fmt = (n?: number, d = 2) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: d }) : '—'
  const fmtMoney = (n?: number) => n != null ? '$' + fmt(n, n > 1000 ? 0 : 2) : '—'
  const pct = (n?: number) => n != null ? (
    <span className={n >= 0 ? 'positive mono' : 'negative mono'}>{n >= 0 ? '+' : ''}{n.toFixed(2)}%</span>
  ) : '—'

  const openAsset = (q: any) => navigate(`/asset/${q.symbol}?class=${market}`)

  if (loading) return (
    <div className="muted" style={{ padding: 40, textAlign: 'center' }}>
      <span className="live-dot" /> Loading {cfg.title}…
    </div>
  )
  if (error && quotes.length === 0) return <div className="negative">{error}</div>

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>{cfg.title}</h2>
          <p className="muted" style={{ fontSize: 12 }}>{cfg.subtitle}</p>
        </div>
        <div className="flex gap-8" style={{ alignItems: 'center' }}>
          {refreshing && <span className="live-dot" />}
          <button className="btn btn-sm btn-primary" onClick={() => load(true)}>Refresh</button>
        </div>
      </div>

      {market === 'crypto' && overview && (
        <div className="panel mb-8">
          <div className="panel-header">
            <span className="panel-title"><span className="live-dot" />Regime</span>
            <span className="badge badge-amber">
              {overview.regime?.replace(/-/g, ' ') || '—'} ({overview.regime_confidence?.toFixed(0)}%)
            </span>
          </div>
          <div className="flex gap-12" style={{ flexWrap: 'wrap' }}>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>Market Cap</div>
              <div className="mono" style={{ fontSize: 16 }}>
                ${overview.total_market_cap ? (overview.total_market_cap / 1e12).toFixed(2) + 'T' : '—'}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>24h Volume</div>
              <div className="mono" style={{ fontSize: 16 }}>
                ${overview.total_volume_24h ? (overview.total_volume_24h / 1e9).toFixed(1) + 'B' : '—'}
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11 }}>BTC Dom</div>
              <div className="mono" style={{ fontSize: 16 }}>
                {overview.btc_dominance ? overview.btc_dominance.toFixed(1) + '%' : '—'}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="grid-12 mb-8">
        <div className="panel col-6">
          <div className="panel-header"><span className="panel-title">Top Gainers</span></div>
          <table className="table">
            <thead><tr><th>Asset</th><th className="text-right">Price</th><th className="text-right">24h</th></tr></thead>
            <tbody>
              {(movers.gainers || []).slice(0, 8).map((m: any) => (
                <tr key={m.symbol} style={{ cursor: 'pointer' }} onClick={() => openAsset(m)}>
                  <td className="mono">{m.symbol}</td>
                  <td className="text-right mono">{cfg.units}{fmt(m.price)}</td>
                  <td className="text-right">{pct(m.change_24h)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="panel col-6">
          <div className="panel-header"><span className="panel-title">Top Losers</span></div>
          <table className="table">
            <thead><tr><th>Asset</th><th className="text-right">Price</th><th className="text-right">24h</th></tr></thead>
            <tbody>
              {(movers.losers || []).slice(0, 8).map((m: any) => (
                <tr key={m.symbol} style={{ cursor: 'pointer' }} onClick={() => openAsset(m)}>
                  <td className="mono">{m.symbol}</td>
                  <td className="text-right mono">{cfg.units}{fmt(m.price)}</td>
                  <td className="text-right">{pct(m.change_24h)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">{cfg.title} — Full Board</span>
          <span className="badge badge-blue">Data source: {quotes.some(q => q.source === 'coingecko') ? 'CoinGecko + demo fallback' : 'demo feed'}</span>
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th><th>Name</th><th className="text-right">Price</th>
              <th className="text-right">24h</th><th className="text-right">7d</th><th className="text-right">30d</th>
              <th className="text-right">Volume (24h)</th><th className="text-right">Market Cap</th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((q: any) => (
              <tr key={q.symbol} style={{ cursor: 'pointer' }} onClick={() => openAsset(q)}>
                <td className="mono" style={{ fontWeight: 600 }}>{q.symbol}</td>
                <td className="muted">{q.name}</td>
                <td className="text-right mono">{cfg.units}{fmt(q.price)}</td>
                <td className="text-right">{pct(q.change_24h)}</td>
                <td className="text-right">{pct(q.change_7d)}</td>
                <td className="text-right">{pct(q.change_30d)}</td>
                <td className="text-right mono">{q.volume_24h ? '$' + fmt(q.volume_24h) : '—'}</td>
                <td className="text-right mono">{q.market_cap ? '$' + fmt(q.market_cap) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted mt-8" style={{ fontSize: 11 }}>
          Demo and live feeds are for research & simulation only. Not financial advice.
        </p>
      </div>
    </div>
  )
}
