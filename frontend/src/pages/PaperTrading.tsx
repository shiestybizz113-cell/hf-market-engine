import { useEffect, useState } from 'react'
import { getPaperTrades, openPaperTrade, closePaperTrade } from '../services/api'
import { Plus, X } from 'lucide-react'

export default function PaperTrading() {
  const [tab, setTab] = useState<'open' | 'closed'>('open')
  const [trades, setTrades] = useState<any[]>([])
  const [showOpen, setShowOpen] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState({
    asset: 'BTC',
    asset_class: 'crypto',
    direction: 'long',
    quantity: 0.1,
    entry_price: '',
    stop_loss: '',
    take_profit: '',
    notes: '',
  })

  const load = () => {
    getPaperTrades(tab).then(r => setTrades(r.data)).catch(() => {})
  }
  useEffect(() => { load() }, [tab])

  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))

  const open = async () => {
    setError('')
    try {
      const payload: any = {
        asset: form.asset.toUpperCase(),
        asset_class: form.asset_class,
        direction: form.direction,
        quantity: +form.quantity,
        notes: form.notes || undefined,
      }
      if (form.entry_price) payload.entry_price = +form.entry_price
      if (form.stop_loss) payload.stop_loss = +form.stop_loss
      if (form.take_profit) payload.take_profit = +form.take_profit
      await openPaperTrade(payload)
      setShowOpen(false)
      setForm({ asset: 'BTC', asset_class: 'crypto', direction: 'long', quantity: 0.1, entry_price: '', stop_loss: '', take_profit: '', notes: '' })
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to open trade')
    }
  }

  const close = async (id: string) => {
    setError('')
    try {
      await closePaperTrade(id)
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to close trade')
    }
  }

  const fmt = (n?: number, d = 2) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: d }) : '—'
  const pnlClass = (n?: number) => n == null ? '' : n >= 0 ? 'positive mono' : 'negative mono'

  const unrealized = trades.reduce((s, t) => s + (t.unrealized_pnl || 0), 0)
  const realized = trades.reduce((s, t) => s + (t.realized_pnl || 0), 0)
  const winCount = trades.filter(t => (t.realized_pnl || 0) > 0).length

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>Paper Trading</h2>
          <p className="muted" style={{ fontSize: 12 }}>Simulated positions with live marks. No real capital.</p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setShowOpen(!showOpen)}>
          <Plus size={14} /> Open Trade
        </button>
      </div>

      <div className="grid-12 mb-8">
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>Open Positions</div>
          <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{trades.filter(t => t.status === 'open').length}</div>
        </div>
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>{tab === 'open' ? 'Unrealized P&L' : 'Closed P&L'}</div>
          <div className={`mono ${pnlClass(tab === 'open' ? unrealized : realized)}`} style={{ fontSize: 20, fontWeight: 600 }}>
            {tab === 'open' ? (unrealized >= 0 ? '+' : '') + fmt(unrealized) : (realized >= 0 ? '+' : '') + fmt(realized)}
          </div>
        </div>
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>Closed Wins</div>
          <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{winCount}</div>
        </div>
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>Win Rate (closed)</div>
          <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{winCount > 0 ? Math.round(winCount / Math.max(trades.length, 1) * 100) : 0}%</div>
        </div>
      </div>

      {showOpen && (
        <div className="panel mb-8">
          <div className="panel-header">
            <span className="panel-title">Open Simulated Trade</span>
            <button className="btn btn-sm" onClick={() => setShowOpen(false)}><X size={13} /></button>
          </div>
          <div className="grid-12">
            <div className="col-2 form-row">
              <label>Asset</label>
              <input value={form.asset} onChange={e => set('asset', e.target.value.toUpperCase())} />
            </div>
            <div className="col-2 form-row">
              <label>Class</label>
              <select value={form.asset_class} onChange={e => set('asset_class', e.target.value)}>
                <option value="crypto">Crypto</option>
                <option value="stock">Stock</option>
                <option value="etf">ETF</option>
              </select>
            </div>
            <div className="col-2 form-row">
              <label>Direction</label>
              <select value={form.direction} onChange={e => set('direction', e.target.value)}>
                <option value="long">Long</option>
                <option value="short">Short</option>
              </select>
            </div>
            <div className="col-2 form-row">
              <label>Quantity</label>
              <input type="number" step="0.001" value={form.quantity} onChange={e => set('quantity', +e.target.value)} />
            </div>
            <div className="col-2 form-row">
              <label>Entry Price (opt)</label>
              <input type="number" step="0.01" value={form.entry_price} placeholder="market" onChange={e => set('entry_price', e.target.value)} />
            </div>
            <div className="col-2 form-row">
              <label>Notes</label>
              <input value={form.notes} onChange={e => set('notes', e.target.value)} />
            </div>
            <div className="col-3 form-row">
              <label>Stop Loss</label>
              <input type="number" step="0.01" value={form.stop_loss} onChange={e => set('stop_loss', e.target.value)} />
            </div>
            <div className="col-3 form-row">
              <label>Take Profit</label>
              <input type="number" step="0.01" value={form.take_profit} onChange={e => set('take_profit', e.target.value)} />
            </div>
          </div>
          <div className="flex gap-8 mt-8">
            <button className="btn btn-primary" onClick={open}>Open Trade</button>
            <button className="btn" onClick={() => setShowOpen(false)}>Cancel</button>
          </div>
          {error && <div className="negative mt-8" style={{ fontSize: 12 }}>{error}</div>}
        </div>
      )}

      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">{tab === 'open' ? 'Open Positions' : 'Closed Trades'}</span>
          <div className="flex gap-8">
            <button className={`btn btn-sm ${tab === 'open' ? 'btn-primary' : ''}`} onClick={() => setTab('open')}>Open</button>
            <button className={`btn btn-sm ${tab === 'closed' ? 'btn-primary' : ''}`} onClick={() => setTab('closed')}>Closed</button>
          </div>
        </div>

        <table className="table">
          <thead>
            <tr>
              <th>Asset</th><th>Dir</th>
              <th className="text-right">Qty</th>
              <th className="text-right">Entry</th>
              <th className="text-right">Mark</th>
              <th className="text-right">Stop</th>
              <th className="text-right">Target</th>
              <th className="text-right">P&L</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr><td colSpan={10} className="muted">No {tab} trades yet.</td></tr>
            ) : trades.map(t => (
              <tr key={t.id}>
                <td className="mono" style={{ fontWeight: 600 }}>{t.asset}</td>
                <td><span className={`badge ${t.direction === 'long' ? 'badge-green' : 'badge-red'}`}>{t.direction}</span></td>
                <td className="text-right mono">{fmt(t.quantity, 4)}</td>
                <td className="text-right mono">${fmt(t.entry_price)}</td>
                <td className="text-right mono">${fmt(t.current_price)}</td>
                <td className="text-right mono">{t.stop_loss != null ? '$' + fmt(t.stop_loss) : '—'}</td>
                <td className="text-right mono">{t.take_profit != null ? '$' + fmt(t.take_profit) : '—'}</td>
                <td className={`text-right ${pnlClass(t.unrealized_pnl ?? t.realized_pnl)}`}>
                  {fmt(t.unrealized_pnl ?? t.realized_pnl)}
                </td>
                <td>
                  <span className={`badge ${t.status === 'open' ? 'badge-green' : t.realized_pnl > 0 ? 'badge-blue' : 'badge-neutral'}`}>
                    {t.status}
                  </span>
                </td>
                <td className="text-right">
                  {t.status === 'open' && (
                    <button className="btn btn-sm btn-amber" onClick={() => close(t.id)}>Close</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Simulated fills at live market prices. Not a brokerage account. Not financial advice.
      </p>
    </div>
  )
}
