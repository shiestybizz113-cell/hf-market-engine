import { useEffect, useState } from 'react'
import { getWatchlist, addWatchlist, removeWatchlist, getPrices } from '../services/api'
import { Plus, Trash2 } from 'lucide-react'

export default function Watchlist() {
  const [items, setItems] = useState<any[]>([])
  const [symbol, setSymbol] = useState('')
  const [assetClass, setAssetClass] = useState('crypto')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    getWatchlist()
      .then(r => setItems(r.data))
      .catch(e => setError(e.response?.data?.detail || 'Failed to load'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const add = async () => {
    if (!symbol.trim()) return
    setError('')
    try {
      await addWatchlist(symbol.trim(), assetClass)
      setSymbol('')
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to add')
    }
  }

  const remove = async (id: string) => {
    await removeWatchlist(id)
    load()
  }

  const fmt = (n?: number) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'
  const pct = (n?: number) => n != null ? (
    <span className={n >= 0 ? 'positive mono' : 'negative mono'}>{n >= 0 ? '+' : ''}{n.toFixed(2)}%</span>
  ) : '—'

  return (
    <div>
      <div className="flex-between mb-8">
        <h2 style={{ fontSize: 18 }}>Watchlist</h2>
        <span className="badge badge-neutral">Free: max 10 · Pro: unlimited</span>
      </div>

      <div className="panel mb-8">
        <div className="flex gap-8" style={{ alignItems: 'flex-end' }}>
          <div style={{ flex: 1 }}>
            <label>Symbol</label>
            <input value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="BTC, AAPL, SPY…" />
          </div>
          <div style={{ width: 140 }}>
            <label>Asset Class</label>
            <select value={assetClass} onChange={e => setAssetClass(e.target.value)}>
              <option value="crypto">Crypto</option>
              <option value="stock">Stock</option>
              <option value="etf">ETF</option>
              <option value="macro">Macro</option>
            </select>
          </div>
          <button className="btn btn-primary" onClick={add}><Plus size={14} /> Add</button>
        </div>
        {error && <div className="negative mt-8" style={{ fontSize: 12 }}>{error}</div>}
      </div>

      <div className="panel">
        {loading ? <div className="muted">Loading…</div> : items.length === 0 ? (
          <div className="muted">No assets yet. Add symbols above.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Class</th>
                <th className="text-right">Price</th>
                <th className="text-right">24h</th>
                <th className="text-right">7d</th>
                <th className="text-right">Volume</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr key={item.id}>
                  <td className="mono" style={{ fontWeight: 600 }}>{item.symbol}</td>
                  <td><span className="badge badge-neutral">{item.asset_class}</span></td>
                  <td className="text-right mono">${fmt(item.price)}</td>
                  <td className="text-right">{pct(item.change_24h)}</td>
                  <td className="text-right">{pct(item.change_7d)}</td>
                  <td className="text-right mono">{item.volume ? (item.volume / 1e6).toFixed(1) + 'M' : '—'}</td>
                  <td>
                    <button className="btn btn-sm" onClick={() => remove(item.id)} title="Remove">
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Prices via CoinGecko (crypto) or demo feed (stocks/ETFs). Research only.
      </p>
    </div>
  )
}
