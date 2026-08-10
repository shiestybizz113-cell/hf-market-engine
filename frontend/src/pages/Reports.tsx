import { useEffect, useMemo, useState } from 'react'
import {
  getPaperTrades, getJournal, listExecutionOrders, getPortfolio,
} from '../services/api'

export default function Reports() {
  const [closed, setClosed] = useState<any[]>([])
  const [open, setOpen] = useState<any[]>([])
  const [journal, setJournal] = useState<any[]>([])
  const [orders, setOrders] = useState<any[]>([])
  const [portfolio, setPortfolio] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = () => {
    setLoading(true)
    Promise.all([
      getPaperTrades('closed').then(r => setClosed(r.data || [])).catch(() => {}),
      getPaperTrades('open').then(r => setOpen(r.data || [])).catch(() => {}),
      getJournal().then(r => setJournal(r.data || [])).catch(() => {}),
      listExecutionOrders().then(r => setOrders(r.data || [])).catch(() => {}),
      getPortfolio().then(r => setPortfolio(r.data || [])).catch(() => {}),
    ]).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const stats = useMemo(() => {
    const realized = closed.reduce((a, t) => a + (t.realized_pnl || 0), 0)
    const unrealized = open.reduce((a, t) => a + (t.unrealized_pnl || 0), 0)
    const wins = closed.filter(t => (t.realized_pnl || 0) > 0).length
    const winRate = closed.length ? (wins / closed.length) * 100 : 0
    const best = closed.reduce((a, b) => ((b.realized_pnl || 0) > (a?.realized_pnl || 0) ? b : a), null)
    const worst = closed.reduce((a, b) => ((b.realized_pnl || 0) < (a?.realized_pnl || 0) ? b : a), null)
    const avgWin = wins ? closed.filter(t => (t.realized_pnl || 0) > 0).reduce((a, t) => a + (t.realized_pnl || 0), 0) / wins : 0
    const avgLossArr = closed.filter(t => (t.realized_pnl || 0) <= 0)
    const avgLoss = avgLossArr.length ? avgLossArr.reduce((a, t) => a + (t.realized_pnl || 0), 0) / avgLossArr.length : 0
    const holdValue = portfolio.reduce((a, h) => a + (h.current_value || 0), 0)
    const holdPnl = portfolio.reduce((a, h) => a + (h.unrealized_pnl || 0), 0)
    return { realized, unrealized, wins, winRate, best, worst, avgWin, avgLoss, holdValue, holdPnl }
  }, [closed, open, portfolio])

  const execution = useMemo(() => {
    const byStatus: Record<string, number> = {}
    const byAlgo: Record<string, number> = {}
    let filledQty = 0
    orders.forEach(o => {
      byStatus[o.status] = (byStatus[o.status] || 0) + 1
      const algo = o.algo?.algo_type || 'n/a'
      byAlgo[algo] = (byAlgo[algo] || 0) + 1
      filledQty += o.filled_qty || 0
    })
    const isBps = (o: any) => (o.implementation_shortfall_bps ?? o.vwap_deviation_bps ?? null) != null
    const avgShortfall = orders.filter(isBps).length
      ? orders.reduce((a, o) => a + (o.implementation_shortfall_bps ?? o.vwap_deviation_bps ?? 0), 0) / orders.filter(isBps).length
      : null
    return { byStatus, byAlgo, filledQty, avgShortfall, total: orders.length }
  }, [orders])

  const journalStats = useMemo(() => {
    const mistakes: Record<string, number> = {}
    const emotions: Record<string, number> = {}
    journal.forEach(e => {
      if (e.mistake_tag) mistakes[e.mistake_tag] = (mistakes[e.mistake_tag] || 0) + 1
      if (e.emotion) emotions[e.emotion] = (emotions[e.emotion] || 0) + 1
    })
    const topMistake = Object.entries(mistakes).sort((a, b) => b[1] - a[1])[0]
    const topEmotion = Object.entries(emotions).sort((a, b) => b[1] - a[1])[0]
    return { mistakes, emotions, topMistake, topEmotion }
  }, [journal])

  const fmt = (n?: number, d = 2) => n != null ? n.toLocaleString(undefined, { maximumFractionDigits: d }) : '—'
  const money = (n?: number, d = 2) => n != null ? (
    <span className={n >= 0 ? 'positive mono' : 'negative mono'}>{n >= 0 ? '+' : '−'}${fmt(Math.abs(n), d)}</span>
  ) : '—'
  const pct = (n?: number) => n != null ? n.toFixed(1) + '%' : '—'

  if (loading) return <div className="muted"><span className="live-dot" /> Compiling reports…</div>
  if (error && closed.length === 0) return <div className="negative">{error}</div>

  return (
    <div>
      <div className="flex-between mb-8">
        <div>
          <h2 style={{ fontSize: 18 }}>Performance Reports</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Aggregate P&L, win rate, execution quality and journal analytics from your paper trading lab.
          </p>
        </div>
        <button className="btn btn-sm btn-primary" onClick={load}>Refresh</button>
      </div>

      <div className="grid-12 mb-8">
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Realized P&L</span></div>
          <div style={{ fontSize: 20 }}>{money(stats.realized)}</div>
          <div className="muted" style={{ fontSize: 11 }}>{closed.length} closed trades</div>
        </div>
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Open P&L</span></div>
          <div style={{ fontSize: 20 }}>{money(stats.unrealized)}</div>
          <div className="muted" style={{ fontSize: 11 }}>{open.length} open positions</div>
        </div>
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Win Rate</span></div>
          <div className="mono" style={{ fontSize: 20 }}>{pct(stats.winRate)}</div>
          <div className="muted" style={{ fontSize: 11 }}>{stats.wins} wins / {closed.length} closed</div>
        </div>
        <div className="panel col-3">
          <div className="panel-header"><span className="panel-title">Portfolio Value</span></div>
          <div className="mono" style={{ fontSize: 20 }}>${fmt(stats.holdValue)}</div>
          <div className="muted" style={{ fontSize: 11 }}>{portfolio.length} holdings · {money(stats.holdPnl, 0)} unrealized</div>
        </div>
      </div>

      <div className="grid-12 mb-8">
        <div className="panel col-4">
          <div className="panel-header"><span className="panel-title">Avg Win vs Avg Loss</span></div>
          <div className="flex-between mb-4"><span className="muted" style={{ fontSize: 12 }}>Avg win</span>{money(stats.avgWin)}</div>
          <div className="flex-between mb-4"><span className="muted" style={{ fontSize: 12 }}>Avg loss</span>{money(stats.avgLoss)}</div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Profit factor</span>
            <span className="mono">{stats.avgWin && stats.avgLoss ? (stats.avgWin / Math.abs(stats.avgLoss)).toFixed(2) : '—'}</span>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            Best: {stats.best ? `${stats.best.asset} ${money(stats.best.realized_pnl)}` : '—'}
          </div>
          <div className="muted" style={{ fontSize: 11 }}>
            Worst: {stats.worst ? `${stats.worst.asset} ${money(stats.worst.realized_pnl)}` : '—'}
          </div>
        </div>

        <div className="panel col-4">
          <div className="panel-header"><span className="panel-title">Execution Quality</span></div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Orders</span>
            <span className="mono">{execution.total}</span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Total filled qty</span>
            <span className="mono">{fmt(execution.filledQty)}</span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Avg slippage</span>
            <span className="mono">{execution.avgShortfall != null ? execution.avgShortfall.toFixed(1) + ' bps' : '—'}</span>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            Status: {Object.entries(execution.byStatus).map(([k, v]) => `${k} ${v}`).join(' · ') || 'no orders'}
          </div>
          <div className="muted" style={{ fontSize: 11 }}>
            Algos: {Object.entries(execution.byAlgo).map(([k, v]) => `${k} ×${v}`).join(' · ') || '—'}
          </div>
        </div>

        <div className="panel col-4">
          <div className="panel-header"><span className="panel-title">Journal Signals</span></div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Entries</span>
            <span className="mono">{journal.length}</span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Top mistake</span>
            <span className="mono" style={{ fontSize: 12 }}>
              {journalStats.topMistake ? `${journalStats.topMistake[0]} (${journalStats.topMistake[1]})` : '—'}
            </span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Top emotion</span>
            <span className="mono" style={{ fontSize: 12 }}>
              {journalStats.topEmotion ? `${journalStats.topEmotion[0]} (${journalStats.topEmotion[1]})` : '—'}
            </span>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>
            {journalStats.topMistake ? 'Consider a rule to address the most frequent mistake.' : 'No mistakes tagged yet.'}
          </div>
        </div>
      </div>

      <div className="grid-12">
        <div className="panel col-6">
          <div className="panel-header"><span className="panel-title">Recent Closed Trades</span></div>
          <table className="table">
            <thead><tr><th>Asset</th><th>Dir</th><th className="text-right">P&L</th><th>Closed</th></tr></thead>
            <tbody>
              {closed.slice(-6).reverse().map((t: any) => (
                <tr key={t.id}>
                  <td className="mono">{t.asset}</td>
                  <td>{t.direction === 'short' ? <span className="badge badge-neutral">short</span> : <span className="badge badge-green">long</span>}</td>
                  <td className="text-right">{money(t.realized_pnl)}</td>
                  <td className="muted" style={{ fontSize: 11 }}>
                    {t.closed_at ? new Date(t.closed_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
              {closed.length === 0 && <tr><td colSpan={4} className="muted">No closed trades yet.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="panel col-6">
          <div className="panel-header"><span className="panel-title">Recent Journal Entries</span></div>
          <table className="table">
            <thead><tr><th>Asset</th><th>Emotion</th><th>Mistake</th><th>Lesson</th></tr></thead>
            <tbody>
              {journal.slice(-6).reverse().map((e: any) => (
                <tr key={e.id}>
                  <td className="mono">{e.asset}</td>
                  <td style={{ fontSize: 12 }}>{e.emotion || '—'}</td>
                  <td style={{ fontSize: 12 }}>{e.mistake_tag || '—'}</td>
                  <td className="muted" style={{ fontSize: 11 }}>{e.lesson || '—'}</td>
                </tr>
              ))}
              {journal.length === 0 && <tr><td colSpan={4} className="muted">No journal entries yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Reports aggregate paper-trading simulation data only. Not financial advice.
      </p>
    </div>
  )
}
