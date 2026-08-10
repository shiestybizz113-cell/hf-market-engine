import { useEffect, useState } from 'react'
import { getPlans, getBillingMe, createCheckout, devUpgrade, getMe } from '../services/api'

export default function Pricing() {
  const [plans, setPlans] = useState<any[]>([])
  const [currentPlan, setCurrentPlan] = useState('free')
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  const load = () => {
    getPlans().then(r => setPlans(r.data || [])).catch(() => {})
    getBillingMe()
      .then(r => setCurrentPlan(r.data.plan || 'free'))
      .catch(() => {
        getMe().then(r => setCurrentPlan(r.data.plan || 'free')).catch(() => {})
      })
  }
  useEffect(() => { load() }, [])

  const upgrade = async (planId: string) => {
    if (planId === 'free') return
    setBusy(planId)
    setError('')
    setMsg('')
    try {
      const r = await createCheckout(planId)
      if (r.data?.url) {
        window.location.href = r.data.url
        return
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail || ''
      if (e.response?.status === 503 || String(detail).includes('Stripe')) {
        try {
          const d = await devUpgrade(planId)
          setMsg(`Dev mode: plan set to ${d.data.plan}. Reload features to see unlocked gates.`)
          setCurrentPlan(d.data.plan)
          load()
          return
        } catch (e2: any) {
          setError(e2.response?.data?.detail || 'Upgrade failed')
          return
        }
      }
      setError(detail || 'Checkout failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 22, marginBottom: 6 }}>Pricing</h2>
        <p className="muted">
          Start with market intelligence. Upgrade when you need AI signals, backtesting, paper trading, and risk control.
        </p>
        <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>
          Current plan: <span className="badge badge-blue">{currentPlan}</span>
        </p>
      </div>

      {msg && <div className="panel mb-8" style={{ borderColor: 'var(--positive)' }}><span className="positive">{msg}</span></div>}
      {error && <div className="panel mb-8" style={{ borderColor: 'var(--negative)' }}><span className="negative">{error}</span></div>}

      <div className="grid-12">
        {plans.map((p) => (
          <div key={p.id} className="panel col-4" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="panel-header">
              <span className="panel-title">{p.name}</span>
              {p.id === 'advanced' && <span className="badge badge-blue">Popular</span>}
              {p.id === currentPlan && <span className="badge badge-green">Active</span>}
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
              {(p.features || []).map((f: string, i: number) => (
                <li key={i} style={{ padding: '4px 0', fontSize: 12, borderBottom: '1px solid var(--border)' }}>
                  {f}
                </li>
              ))}
            </ul>
            <button
              className={`btn ${p.id === currentPlan || p.id === 'free' ? '' : 'btn-primary'}`}
              style={{ width: '100%' }}
              disabled={p.id === currentPlan || p.id === 'free' || busy === p.id}
              onClick={() => upgrade(p.id)}
            >
              {p.id === currentPlan
                ? 'Current Plan'
                : p.id === 'free'
                  ? 'Included'
                  : busy === p.id
                    ? 'Working…'
                    : 'Upgrade'}
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
        <p className="muted mt-8" style={{ fontSize: 11 }}>
          Dev tip: without Stripe keys, Upgrade uses /api/billing/dev-upgrade so you can test plan gates.
          With sk_test_ keys, Checkout runs in Stripe Test mode (card 4242…).
        </p>
      </div>
    </div>
  )
}
