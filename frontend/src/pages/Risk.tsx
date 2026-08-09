import { useState } from 'react'
import { riskReviewStrategy, riskReviewPaper } from '../services/api'
import { Shield } from 'lucide-react'

export default function Risk() {
  const [mode, setMode] = useState<'strategy' | 'trade'>('strategy')
  const [result, setResult] = useState<any>(null)
  const [error, setError] = useState('')

  const [strategy, setStrategy] = useState({
    name: 'Test Strategy',
    asset: 'BTC',
    asset_class: 'crypto',
    timeframe: '1h',
    entry_condition: 'RSI < 30',
    exit_condition: 'RSI > 70',
    stop_loss_pct: 2.5,
    take_profit_pct: 6,
    max_position_pct: 5,
    max_daily_loss_pct: 3,
  })

  const [trade, setTrade] = useState({
    asset: 'BTC',
    asset_class: 'crypto',
    direction: 'long',
    quantity: 0.1,
    entry_price: 60000,
    stop_loss: 58000,
    take_profit: 65000,
  })

  const run = async () => {
    setError('')
    setResult(null)
    try {
      const r = mode === 'strategy'
        ? await riskReviewStrategy(strategy)
        : await riskReviewPaper(trade)
      setResult(r.data)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Risk engine error')
    }
  }

  const levelColor = (l: string) =>
    l === 'low' ? 'badge-green' : l === 'medium' ? 'badge-amber' : 'badge-red'

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>Risk Engine</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Score every strategy and paper trade before committing capital (even simulated).
          </p>
        </div>
        <div className="flex gap-8">
          <button className={`btn btn-sm ${mode === 'strategy' ? 'btn-primary' : ''}`} onClick={() => setMode('strategy')}>
            Strategy
          </button>
          <button className={`btn btn-sm ${mode === 'trade' ? 'btn-primary' : ''}`} onClick={() => setMode('trade')}>
            Paper Trade
          </button>
        </div>
      </div>

      <div className="grid-12">
        <div className="panel col-6">
          <div className="panel-header">
            <span className="panel-title">{mode === 'strategy' ? 'Strategy Parameters' : 'Trade Parameters'}</span>
          </div>

          {mode === 'strategy' ? (
            <div className="grid-12">
              <div className="col-6 form-row">
                <label>Stop Loss %</label>
                <input type="number" value={strategy.stop_loss_pct} onChange={e => setStrategy({ ...strategy, stop_loss_pct: +e.target.value })} />
              </div>
              <div className="col-6 form-row">
                <label>Take Profit %</label>
                <input type="number" value={strategy.take_profit_pct} onChange={e => setStrategy({ ...strategy, take_profit_pct: +e.target.value })} />
              </div>
              <div className="col-6 form-row">
                <label>Max Position %</label>
                <input type="number" value={strategy.max_position_pct} onChange={e => setStrategy({ ...strategy, max_position_pct: +e.target.value })} />
              </div>
              <div className="col-6 form-row">
                <label>Max Daily Loss %</label>
                <input type="number" value={strategy.max_daily_loss_pct} onChange={e => setStrategy({ ...strategy, max_daily_loss_pct: +e.target.value })} />
              </div>
            </div>
          ) : (
            <div className="grid-12">
              <div className="col-4 form-row">
                <label>Asset</label>
                <input value={trade.asset} onChange={e => setTrade({ ...trade, asset: e.target.value })} />
              </div>
              <div className="col-4 form-row">
                <label>Quantity</label>
                <input type="number" value={trade.quantity} onChange={e => setTrade({ ...trade, quantity: +e.target.value })} />
              </div>
              <div className="col-4 form-row">
                <label>Entry Price</label>
                <input type="number" value={trade.entry_price} onChange={e => setTrade({ ...trade, entry_price: +e.target.value })} />
              </div>
              <div className="col-6 form-row">
                <label>Stop Loss</label>
                <input type="number" value={trade.stop_loss || ''} onChange={e => setTrade({ ...trade, stop_loss: +e.target.value })} />
              </div>
              <div className="col-6 form-row">
                <label>Take Profit</label>
                <input type="number" value={trade.take_profit || ''} onChange={e => setTrade({ ...trade, take_profit: +e.target.value })} />
              </div>
            </div>
          )}

          <button className="btn btn-primary mt-12" onClick={run}>
            <Shield size={14} /> Run Risk Engine
          </button>
          {error && <div className="negative mt-8" style={{ fontSize: 12 }}>{error}</div>}
        </div>

        <div className="panel col-6">
          <div className="panel-header"><span className="panel-title">Risk Output</span></div>
          {!result ? (
            <div className="muted">Run the engine to see score, level, factors and mitigation.</div>
          ) : (
            <>
              <div className="flex-between mb-8">
                <div>
                  <div className="muted" style={{ fontSize: 11 }}>Risk Score</div>
                  <div className="mono" style={{ fontSize: 32, fontWeight: 600 }}>{result.score}</div>
                </div>
                <span className={`badge ${levelColor(result.level)}`} style={{ fontSize: 12, padding: '4px 10px' }}>
                  {result.level?.toUpperCase()}
                </span>
              </div>
              {result.trade_blocked && (
                <div className="negative mb-8" style={{ fontWeight: 600 }}>TRADE BLOCKED</div>
              )}
              <div className="mb-8">
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Main Risk Factors</div>
                <ul style={{ paddingLeft: 16, fontSize: 12 }}>
                  {result.main_factors?.map((f: string, i: number) => <li key={i}>{f}</li>)}
                </ul>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Suggested Mitigation</div>
                <ul style={{ paddingLeft: 16, fontSize: 12 }}>
                  {result.suggested_mitigation?.map((f: string, i: number) => <li key={i}>{f}</li>)}
                </ul>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="panel mt-8">
        <div className="panel-header"><span className="panel-title">Risk Checks Performed</span></div>
        <div className="grid-12" style={{ fontSize: 12 }}>
          {['Max position size', 'Max daily loss', 'Portfolio concentration', 'Volatility risk',
            'Liquidity risk', 'Correlation risk', 'Drawdown risk', 'Leverage warning',
            'Market regime warning', 'Kill-switch recommendation'].map(c => (
            <div key={c} className="col-4" style={{ padding: '4px 0' }}>• {c}</div>
          ))}
        </div>
      </div>
    </div>
  )
}
