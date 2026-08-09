import { useEffect, useState } from 'react'
import { getPlans } from '../services/api'

export default function Pricing() {
  const [plans, setPlans] = useState<any[]>([])

  useEffect(() => {
    getPlans().then(r => setPlans(r.data)).catch(() => {})
  }, [])

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, marginBottom: 6 }}>Pricing</h2>
        <p className="muted">
          Start with market intelligence. Upgrade when you need AI signals, backtesting, paper trading, and risk control.
        </p>
      </div>

      <div className="grid-12">
        {plans.map((p) => (
          <div key={p.id} className="panel col-4" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="panel-header">
              <span className="panel-title">{p.name}</span>
              {p.id === 'advanced' && <span className="badge badge-blue">Popular</span>}
            </div>
            <div style={{ marginBottom: 12 }}>
              <span className="mono" style={{ fontSize: 28, fontWeight: 600 }}>
                ${p.price_monthly}
              </span>
              <span className="muted">/mo</span>
              {p.setup_fee > 0 && (
                <div className="muted" style={{ fontSize: 11 }}>+ ${p.setup_fee.toLocaleString()} setup</div>
              )}
            </div>
            <ul style={{ listStyle: 'none', flex: 1, marginBottom: 16 }}>
              {p.features.map((f: string, i: number) => (
                <li key={i} style={{ padding: '4px 0', fontSize: 12, borderBottom: '1px solid var(--border)' }}>
                  {f}
                </li>
              ))}
            </ul>
            <button className={`btn ${p.id === 'free' ? '' : 'btn-primary'}`} style={{ width: '100%' }}>
              {p.id === 'free' ? 'Current Plan' : 'Upgrade — Billing coming soon'}
            </button>
          </div>
        ))}
      </div>

      <div className="panel mt-12" style={{ borderColor: 'var(--amber)' }}>
        <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          <strong className="amber">Important:</strong> hf-market-engine does not guarantee trading profits.
          Paid plans provide research tools, simulations, analytics, and AI-assisted decision support.
          This is not financial advice. Trading involves substantial risk of loss.
        </p>
      </div>
    </div>
  )
}
