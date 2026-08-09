import { useState } from 'react'
import { runBacktest } from '../services/api'
import { LineChart as ChartIcon } from 'lucide-react'

export default function Backtesting() {
  const [form, setForm] = useState({
    name: 'BTC RSI Mean Reversion',
    asset: 'BTC',
    asset_class: 'crypto',
    timeframe: '1h',
    entry_condition: 'RSI < 30 AND volume > 20-day avg',
    exit_condition: 'RSI > 70 OR stop/target',
    stop_loss_pct: 2.5,
    take_profit_pct: 6.0,
    max_position_pct: 5.0,
    max_daily_loss_pct: 3.0,
  })
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const set = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))

  const run = async () => {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const r = await runBacktest({
        strategy: form,
        initial_capital: 10000,
      })
      setResult(r.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Backtest failed (Pro plan required)')
    } finally {
      setLoading(false)
    }
  }

  const fmt = (n?: number) => n != null ? n.toFixed(2) : '—'

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>Backtesting</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Simulated historical analysis only. Past performance ≠ future results.
          </p>
        </div>
      </div>

      <div className="grid-12">
        <div className="panel col-5">
          <div className="panel-header"><span className="panel-title">Strategy Inputs</span></div>
          <div className="form-row">
            <label>Strategy Name</label>
            <input value={form.name} onChange={e => set('name', e.target.value)} />
          </div>
          <div className="grid-12">
            <div className="col-6 form-row">
              <label>Asset</label>
              <input value={form.asset} onChange={e => set('asset', e.target.value.toUpperCase())} />
            </div>
            <div className="col-6 form-row">
              <label>Timeframe</label>
              <select value={form.timeframe} onChange={e => set('timeframe', e.target.value)}>
                <option value="15m">15m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>
          </div>
          <div className="form-row">
            <label>Entry Condition</label>
            <textarea rows={2} value={form.entry_condition} onChange={e => set('entry_condition', e.target.value)} />
          </div>
          <div className="form-row">
            <label>Exit Condition</label>
            <textarea rows={2} value={form.exit_condition} onChange={e => set('exit_condition', e.target.value)} />
          </div>
          <div className="grid-12">
            <div className="col-6 form-row">
              <label>Stop Loss %</label>
              <input type="number" value={form.stop_loss_pct} onChange={e => set('stop_loss_pct', +e.target.value)} />
            </div>
            <div className="col-6 form-row">
              <label>Take Profit %</label>
              <input type="number" value={form.take_profit_pct} onChange={e => set('take_profit_pct', +e.target.value)} />
            </div>
          </div>
          <button className="btn btn-primary" onClick={run} disabled={loading} style={{ width: '100%' }}>
            <ChartIcon size={14} /> {loading ? 'Running…' : 'Run Backtest'}
          </button>
          {error && <div className="negative mt-8" style={{ fontSize: 12 }}>{error}</div>}
        </div>

        <div className="panel col-7">
          <div className="panel-header">
            <span className="panel-title">Results</span>
            {result && <span className="badge badge-amber">SIMULATED</span>}
          </div>
          {!result ? (
            <div className="muted">Configure a strategy and run the backtest.</div>
          ) : (
            <>
              <div className="grid-12" style={{ marginBottom: 16 }}>
                {[
                  { label: 'Total Return', value: `${fmt(result.total_return_pct)}%`, cls: result.total_return_pct >= 0 ? 'positive' : 'negative' },
                  { label: 'Win Rate', value: `${fmt(result.win_rate)}%` },
                  { label: 'Max Drawdown', value: `${fmt(result.max_drawdown_pct)}%`, cls: 'negative' },
                  { label: 'Profit Factor', value: fmt(result.profit_factor) },
                  { label: 'Trades', value: result.number_of_trades },
                  { label: 'Avg Trade', value: `${fmt(result.average_trade_pct)}%` },
                  { label: 'Best Trade', value: `${fmt(result.best_trade_pct)}%`, cls: 'positive' },
                  { label: 'Worst Trade', value: `${fmt(result.worst_trade_pct)}%`, cls: 'negative' },
                ].map(m => (
                  <div key={m.label} className="col-3" style={{ marginBottom: 10 }}>
                    <div className="muted" style={{ fontSize: 10 }}>{m.label}</div>
                    <div className={`mono ${m.cls || ''}`} style={{ fontSize: 16, fontWeight: 600 }}>{m.value}</div>
                  </div>
                ))}
              </div>

              <div className="mb-8">
                <div className="muted" style={{ fontSize: 11 }}>Overfit Risk Score</div>
                <div className="mono" style={{ fontSize: 20 }}>{fmt(result.overfit_risk_score)} / 100</div>
              </div>

              <div className="panel" style={{ background: 'var(--bg)', borderColor: 'var(--amber)' }}>
                <div className="panel-title amber" style={{ marginBottom: 6 }}>AI Strategy Review</div>
                <p style={{ fontSize: 12, lineHeight: 1.5 }}>{result.ai_review}</p>
              </div>

              {result.equity_curve?.length > 0 && (
                <div className="mt-12">
                  <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>Equity Curve (simulated)</div>
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: 1, height: 60 }}>
                    {result.equity_curve.filter((_: any, i: number) => i % 3 === 0).map((p: any, i: number) => {
                      const max = Math.max(...result.equity_curve.map((x: any) => x.equity))
                      const min = Math.min(...result.equity_curve.map((x: any) => x.equity))
                      const h = ((p.equity - min) / (max - min + 1)) * 56 + 4
                      return (
                        <div
                          key={i}
                          title={`Day ${p.day}: $${p.equity}`}
                          style={{
                            flex: 1,
                            height: h,
                            background: p.equity >= 10000 ? 'var(--positive)' : 'var(--negative)',
                            opacity: 0.7,
                            borderRadius: 1,
                          }}
                        />
                      )
                    })}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="panel mt-8" style={{ borderColor: 'var(--amber)' }}>
        <p style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          <strong className="amber">Simulated historical analysis only.</strong> This backtest does not guarantee future performance.
          Results are for research and education. Not financial advice.
        </p>
      </div>
    </div>
  )
}
