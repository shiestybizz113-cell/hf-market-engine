import { useEffect, useState } from 'react'
import { getStrategies, createStrategy, deleteStrategy, riskReviewStrategy } from '../services/api'
import { Plus, Trash2, Shield } from 'lucide-react'

const empty = {
  name: '',
  asset: 'BTC',
  asset_class: 'crypto',
  timeframe: '1h',
  entry_condition: 'RSI < 30 AND volume > 20-day average',
  exit_condition: 'RSI > 70 OR stop/target hit',
  stop_loss_pct: 2.5,
  take_profit_pct: 6.0,
  max_position_pct: 5.0,
  max_daily_loss_pct: 3.0,
  notes: '',
}

export default function Strategies() {
  const [list, setList] = useState<any[]>([])
  const [form, setForm] = useState({ ...empty })
  const [risk, setRisk] = useState<any>(null)
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState('')

  const load = () => getStrategies().then(r => setList(r.data)).catch(() => {})
  useEffect(() => { load() }, [])

  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))

  const reviewRisk = async () => {
    try {
      const r = await riskReviewStrategy(form)
      setRisk(r.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Risk review failed')
    }
  }

  const save = async () => {
    setError('')
    try {
      await createStrategy(form)
      setForm({ ...empty })
      setShowForm(false)
      setRisk(null)
      load()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Save failed')
    }
  }

  const remove = async (id: string) => {
    await deleteStrategy(id)
    load()
  }

  return (
    <div>
      <div className="flex-between mb-8">
        <h2 style={{ fontSize: 18 }}>Strategy Lab</h2>
        <button className="btn btn-primary btn-sm" onClick={() => setShowForm(!showForm)}>
          <Plus size={14} /> New Strategy
        </button>
      </div>

      {showForm && (
        <div className="panel mb-8">
          <div className="panel-header"><span className="panel-title">Create Rule-Based Strategy</span></div>
          <div className="grid-12">
            <div className="col-4 form-row">
              <label>Name</label>
              <input value={form.name} onChange={e => set('name', e.target.value)} placeholder="BTC RSI Mean Reversion" />
            </div>
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
              <label>Timeframe</label>
              <select value={form.timeframe} onChange={e => set('timeframe', e.target.value)}>
                <option value="15m">15m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>
            <div className="col-6 form-row">
              <label>Entry Condition</label>
              <textarea rows={2} value={form.entry_condition} onChange={e => set('entry_condition', e.target.value)} />
            </div>
            <div className="col-6 form-row">
              <label>Exit Condition</label>
              <textarea rows={2} value={form.exit_condition} onChange={e => set('exit_condition', e.target.value)} />
            </div>
            <div className="col-3 form-row">
              <label>Stop Loss %</label>
              <input type="number" step="0.1" value={form.stop_loss_pct} onChange={e => set('stop_loss_pct', +e.target.value)} />
            </div>
            <div className="col-3 form-row">
              <label>Take Profit %</label>
              <input type="number" step="0.1" value={form.take_profit_pct} onChange={e => set('take_profit_pct', +e.target.value)} />
            </div>
            <div className="col-3 form-row">
              <label>Max Position %</label>
              <input type="number" step="0.5" value={form.max_position_pct} onChange={e => set('max_position_pct', +e.target.value)} />
            </div>
            <div className="col-3 form-row">
              <label>Max Daily Loss %</label>
              <input type="number" step="0.5" value={form.max_daily_loss_pct} onChange={e => set('max_daily_loss_pct', +e.target.value)} />
            </div>
            <div className="col-12 form-row">
              <label>Notes</label>
              <input value={form.notes} onChange={e => set('notes', e.target.value)} />
            </div>
          </div>

          {risk && (
            <div className="panel mt-8" style={{ borderColor: risk.level === 'extreme' || risk.level === 'high' ? 'var(--negative)' : 'var(--border)' }}>
              <div className="flex-between">
                <span className="panel-title">Risk Review</span>
                <span className={`badge ${risk.level === 'low' ? 'badge-green' : risk.level === 'medium' ? 'badge-amber' : 'badge-red'}`}>
                  {risk.level} · {risk.score}/100
                </span>
              </div>
              <div style={{ fontSize: 12 }}>
                <strong>Factors:</strong> {risk.main_factors?.join(' · ')}
              </div>
              <div className="muted mt-8" style={{ fontSize: 12 }}>
                <strong>Mitigation:</strong> {risk.suggested_mitigation?.join(' · ')}
              </div>
              {risk.trade_blocked && <div className="negative mt-8">Trade blocked under current risk rules.</div>}
            </div>
          )}

          <div className="flex gap-8 mt-12">
            <button className="btn btn-amber" onClick={reviewRisk}><Shield size={14} /> AI Risk Review</button>
            <button className="btn btn-primary" onClick={save}>Save Strategy</button>
            <button className="btn" onClick={() => { setShowForm(false); setRisk(null) }}>Cancel</button>
          </div>
          {error && <div className="negative mt-8" style={{ fontSize: 12 }}>{error}</div>}
        </div>
      )}

      <div className="panel">
        <div className="panel-header"><span className="panel-title">Saved Strategies</span></div>
        {list.length === 0 ? (
          <div className="muted">No strategies yet. Create one to start testing.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Asset</th>
                <th>TF</th>
                <th>SL%</th>
                <th>TP%</th>
                <th>Max Pos%</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map(s => (
                <tr key={s.id}>
                  <td style={{ fontWeight: 600 }}>{s.name}</td>
                  <td className="mono">{s.asset}</td>
                  <td>{s.timeframe}</td>
                  <td className="mono">{s.stop_loss_pct}%</td>
                  <td className="mono">{s.take_profit_pct}%</td>
                  <td className="mono">{s.max_position_pct}%</td>
                  <td>
                    <button className="btn btn-sm" onClick={() => remove(s.id)}><Trash2 size={12} /></button>
                    <a className="btn btn-sm" href="/paper" title="Open Execution Sim">Sim Exec</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Strategies are for research and paper trading only. Not financial advice.
      </p>
    </div>
  )
}
