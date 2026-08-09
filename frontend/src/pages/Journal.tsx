import { useEffect, useState } from 'react'
import api from '../services/api'
import { Plus } from 'lucide-react'

export default function Journal() {
  const [entries, setEntries] = useState<any[]>([])
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({
    asset: '',
    direction: 'long',
    entry_price: 0,
    exit_price: '',
    quantity: 0,
    pnl: '',
    notes: '',
    emotion: '',
    mistake_tag: '',
    lesson: '',
  })
  const [error, setError] = useState('')

  const load = () => {
    api.get('/journal').then(r => setEntries(r.data)).catch(() => {})
  }
  useEffect(() => { load() }, [])

  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))

  const add = async () => {
    setError('')
    try {
      await api.post('/journal', {
        ...form,
        exit_price: form.exit_price ? +form.exit_price : null,
        pnl: form.pnl !== '' ? +form.pnl : null,
      })
      setShowAdd(false)
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Failed to save')
    }
  }

  const fmt = (n?: number) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'
  const pnlClass = (n?: number) => n == null ? '' : n >= 0 ? 'positive mono' : 'negative mono'
  const sourceBadge = (s: string) => {
    if (s === 'paper_trade') return 'badge-blue'
    if (s === 'execution_sim') return 'badge-amber'
    return 'badge-neutral'
  }

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>Trade Journal</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Auto-populated from closed paper trades and execution sims. Add manual notes anytime.
          </p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(!showAdd)}>
          <Plus size={14} /> Manual Entry
        </button>
      </div>

      {showAdd && (
        <div className="panel mb-8">
          <div className="panel-header"><span className="panel-title">Manual Journal Entry</span></div>
          <div className="grid-12">
            <div className="col-2 form-row">
              <label>Asset</label>
              <input value={form.asset} onChange={e => set('asset', e.target.value.toUpperCase())} />
            </div>
            <div className="col-2 form-row">
              <label>Direction</label>
              <select value={form.direction} onChange={e => set('direction', e.target.value)}>
                <option value="long">Long</option>
                <option value="short">Short</option>
              </select>
            </div>
            <div className="col-2 form-row">
              <label>Entry</label>
              <input type="number" value={form.entry_price} onChange={e => set('entry_price', +e.target.value)} />
            </div>
            <div className="col-2 form-row">
              <label>Exit</label>
              <input type="number" value={form.exit_price} onChange={e => set('exit_price', e.target.value)} />
            </div>
            <div className="col-2 form-row">
              <label>Qty</label>
              <input type="number" value={form.quantity} onChange={e => set('quantity', +e.target.value)} />
            </div>
            <div className="col-2 form-row">
              <label>P&L</label>
              <input type="number" value={form.pnl} onChange={e => set('pnl', e.target.value)} />
            </div>
            <div className="col-4 form-row">
              <label>Emotion / Discipline</label>
              <input value={form.emotion} onChange={e => set('emotion', e.target.value)} placeholder="calm, FOMO, revenge…" />
            </div>
            <div className="col-4 form-row">
              <label>Mistake Tag</label>
              <input value={form.mistake_tag} onChange={e => set('mistake_tag', e.target.value)} placeholder="size, timing, no-stop…" />
            </div>
            <div className="col-4 form-row">
              <label>Lesson</label>
              <input value={form.lesson} onChange={e => set('lesson', e.target.value)} />
            </div>
            <div className="col-12 form-row">
              <label>Notes</label>
              <input value={form.notes} onChange={e => set('notes', e.target.value)} />
            </div>
          </div>
          <div className="flex gap-8 mt-8">
            <button className="btn btn-primary" onClick={add}>Save</button>
            <button className="btn" onClick={() => setShowAdd(false)}>Cancel</button>
          </div>
          {error && <div className="negative mt-8" style={{ fontSize: 12 }}>{error}</div>}
        </div>
      )}

      <div className="panel">
        <table className="table">
          <thead>
            <tr>
              <th>Date</th><th>Asset</th><th>Dir</th>
              <th className="text-right">Entry</th><th className="text-right">Exit</th>
              <th className="text-right">P&L</th><th>Source</th><th>AI Review</th>
            </tr>
          </thead>
          <tbody>
            {entries.length === 0 ? (
              <tr><td colSpan={8} className="muted">
                No journal entries yet. Close a paper trade or run an execution sim to auto-populate.
              </td></tr>
            ) : entries.map(e => (
              <tr key={e.id}>
                <td className="mono" style={{ fontSize: 11 }}>
                  {e.trade_date ? new Date(e.trade_date).toLocaleDateString() : '—'}
                </td>
                <td className="mono" style={{ fontWeight: 600 }}>{e.asset}</td>
                <td><span className={`badge ${e.direction === 'long' ? 'badge-green' : 'badge-red'}`}>{e.direction}</span></td>
                <td className="text-right mono">${fmt(e.entry_price)}</td>
                <td className="text-right mono">{e.exit_price != null ? '$' + fmt(e.exit_price) : '—'}</td>
                <td className={`text-right ${pnlClass(e.pnl)}`}>{fmt(e.pnl)}</td>
                <td><span className={`badge ${sourceBadge(e.source)}`}>{e.source?.replace('_', ' ')}</span></td>
                <td style={{ fontSize: 11, maxWidth: 280 }} className="truncate" title={e.ai_review}>
                  {e.ai_review || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Journal is for process review. Auto-entries come from paper closes and execution sims. Not financial advice.
      </p>
    </div>
  )
}
