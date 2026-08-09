import { useEffect, useState } from 'react'
import { getPortfolio, addHolding, getPaperTrades, listExecutionOrders } from '../services/api'
import { Plus } from 'lucide-react'

export default function Portfolio() {
  const [holdings, setHoldings] = useState<any[]>([])
  const [paper, setPaper] = useState<any[]>([])
  const [execs, setExecs] = useState<any[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({
    asset: '',
    asset_class: 'crypto',
    quantity: 1,
    entry_price: 0,
    notes: '',
  })
  const [error, setError] = useState('')

  const load = () => {
    getPortfolio().then(r => setHoldings(r.data)).catch(() => {})
    getPaperTrades('open').then(r => setPaper(r.data)).catch(() => {})
    listExecutionOrders().then(r => setExecs(r.data.slice(0, 10))).catch(() => {})
  }
  useEffect(() => { load() }, [])

  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))

  const add = async () => {
    setError('')
    try {
      await addHolding(form)
      setShowAdd(false)
      setForm({ asset: '', asset_class: 'crypto', quantity: 1, entry_price: 0, notes: '' })
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to add holding')
    }
  }

  const fmt = (n?: number, d = 2) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: d }) : '—'
  const pnlClass = (n?: number) => n == null ? '' : n >= 0 ? 'positive mono' : 'negative mono'

  const totalValue = holdings.reduce((s, h) => s + (h.current_value || 0), 0)
  const totalPnl = holdings.reduce((s, h) => s + (h.unrealized_pnl || 0), 0)
  const paperUnrealized = paper.reduce((s, t) => s + (t.unrealized_pnl || 0), 0)

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>Portfolio / P&L</h2>
          <p className="muted" style={{ fontSize: 12 }}>Manual holdings + open paper positions + recent execution sims</p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(!showAdd)}>
          <Plus size={14} /> Add Holding
        </button>
      </div>

      <div className="grid-12 mb-8">
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>Holdings Value</div>
          <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>${fmt(totalValue)}</div>
        </div>
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>Holdings Unrealized</div>
          <div className={`mono ${pnlClass(totalPnl)}`} style={{ fontSize: 20, fontWeight: 600 }}>
            {totalPnl >= 0 ? '+' : ''}{fmt(totalPnl)}
          </div>
        </div>
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>Open Paper P&L</div>
          <div className={`mono ${pnlClass(paperUnrealized)}`} style={{ fontSize: 20, fontWeight: 600 }}>
            {paperUnrealized >= 0 ? '+' : ''}{fmt(paperUnrealized)}
          </div>
        </div>
        <div className="panel col-3">
          <div className="muted" style={{ fontSize: 10 }}>Open Paper Positions</div>
          <div className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{paper.length}</div>
        </div>
      </div>

      {showAdd && (
        <div className="panel mb-8">
          <div className="panel-header"><span className="panel-title">Add Manual Holding</span></div>
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
              <label>Quantity</label>
              <input type="number" step="0.001" value={form.quantity} onChange={e => set('quantity', +e.target.value)} />
            </div>
            <div className="col-2 form-row">
              <label>Entry Price</label>
              <input type="number" step="0.01" value={form.entry_price} onChange={e => set('entry_price', +e.target.value)} />
            </div>
            <div className="col-4 form-row">
              <label>Notes</label>
              <input value={form.notes} onChange={e => set('notes', e.target.value)} />
            </div>
          </div>
          <div className="flex gap-8 mt-8">
            <button className="btn btn-primary" onClick={add}>Add</button>
            <button className="btn" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
          {error && <div className="negative mt-8" style={{ fontSize: 12 }}>{error}</div>}
        </div>
      )}

      <div className="panel mb-8">
        <div className="panel-header"><span className="panel-title">Manual Holdings</span></div>
        <table className="table">
          <thead>
            <tr>
              <th>Asset</th><th>Class</th><th className="text-right">Qty</th>
              <th className="text-right">Entry</th><th className="text-right">Mark</th>
              <th className="text-right">Value</th><th className="text-right">uPnL</th>
              <th className="text-right">uPnL %</th><th className="text-right">Alloc %</th>
            </tr>
          </thead>
          <tbody>
            {holdings.length === 0 ? (
              <tr><td colSpan={9} className="muted">No holdings. Add manually or use paper trading.</td></tr>
            ) : holdings.map(h => (
              <tr key={h.id}>
                <td className="mono" style={{ fontWeight: 600 }}>{h.asset}</td>
                <td><span className="badge badge-neutral">{h.asset_class}</span></td>
                <td className="text-right mono">{fmt(h.quantity, 4)}</td>
                <td className="text-right mono">${fmt(h.entry_price)}</td>
                <td className="text-right mono">${fmt(h.current_price)}</td>
                <td className="text-right mono">${fmt(h.current_value)}</td>
                <td className={`text-right ${pnlClass(h.unrealized_pnl)}`}>{fmt(h.unrealized_pnl)}</td>
                <td className={`text-right ${pnlClass(h.unrealized_pnl_pct)}`}>{fmt(h.unrealized_pnl_pct)}%</td>
                <td className="text-right mono">{fmt(h.allocation_pct, 1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel mb-8">
        <div className="panel-header"><span className="panel-title">Open Paper Positions</span></div>
        <table className="table">
          <thead>
            <tr>
              <th>Asset</th><th>Dir</th><th className="text-right">Qty</th>
              <th className="text-right">Entry</th><th className="text-right">Mark</th>
              <th className="text-right">uPnL</th>
            </tr>
          </thead>
          <tbody>
            {paper.length === 0 ? (
              <tr><td colSpan={6} className="muted">No open paper positions.</td></tr>
            ) : paper.map(t => (
              <tr key={t.id}>
                <td className="mono">{t.asset}</td>
                <td><span className={`badge ${t.direction === 'long' ? 'badge-green' : 'badge-red'}`}>{t.direction}</span></td>
                <td className="text-right mono">{fmt(t.quantity, 4)}</td>
                <td className="text-right mono">${fmt(t.entry_price)}</td>
                <td className="text-right mono">${fmt(t.current_price)}</td>
                <td className={`text-right ${pnlClass(t.unrealized_pnl)}`}>{fmt(t.unrealized_pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <div className="panel-header"><span className="panel-title">Recent Execution Sims</span></div>
        <table className="table">
          <thead>
            <tr>
              <th>Asset</th><th>Side</th><th>Algo</th>
              <th className="text-right">Filled</th><th className="text-right">Avg</th>
              <th className="text-right">Shortfall bps</th>
            </tr>
          </thead>
          <tbody>
            {execs.length === 0 ? (
              <tr><td colSpan={6} className="muted">No execution sims yet.</td></tr>
            ) : execs.map(o => (
              <tr key={o.id}>
                <td className="mono">{o.asset}</td>
                <td>{o.side}</td>
                <td className="mono">{o.algo?.algo_type}</td>
                <td className="text-right mono">{fmt(o.filled_qty, 4)}</td>
                <td className="text-right mono">${fmt(o.avg_fill_price)}</td>
                <td className={`text-right mono ${(o.implementation_shortfall_bps || 0) > 0 ? 'negative' : 'positive'}`}>
                  {fmt(o.implementation_shortfall_bps)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Simulated / manual tracking only. Not a brokerage account. Not financial advice.
      </p>
    </div>
  )
}
