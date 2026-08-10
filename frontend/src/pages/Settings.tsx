import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMe, getBillingMe, getBillingStatus, getPlans, devUpgrade, devDowngrade } from '../services/api'
import { LogOut, Shield, CreditCard, Database } from 'lucide-react'

export default function Settings() {
  const navigate = useNavigate()
  const [me, setMe] = useState<any>(null)
  const [billing, setBilling] = useState<any>(null)
  const [status, setStatus] = useState<any>(null)
  const [plans, setPlans] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [busy, setBusy] = useState('')

  const load = () => {
    setLoading(true)
    Promise.all([
      getMe().then(r => setMe(r.data)).catch(() => {}),
      getBillingMe().then(r => setBilling(r.data)).catch(() => {}),
      getBillingStatus().then(r => setStatus(r.data)).catch(() => {}),
      getPlans().then(r => setPlans(r.data || [])).catch(() => {}),
    ]).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const doUpgrade = (planId: string) => {
    setBusy(planId)
    setMsg(null)
    devUpgrade(planId)
      .then(() => { setMsg({ ok: true, text: `Switched to ${planId} in dev mode.` }); load() })
      .catch(e => setMsg({ ok: false, text: e.response?.data?.detail || 'Upgrade failed' }))
      .finally(() => setBusy(''))
  }

  const doDowngrade = () => {
    setBusy('free')
    setMsg(null)
    devDowngrade('free')
      .then(() => { setMsg({ ok: true, text: 'Switched back to free plan.' }); load() })
      .catch(e => setMsg({ ok: false, text: e.response?.data?.detail || 'Downgrade failed' }))
      .finally(() => setBusy(''))
  }

  const logout = () => {
    localStorage.removeItem('token')
    navigate('/login')
  }

  if (loading) return <div className="muted"><span className="live-dot" /> Loading settings…</div>

  const plan = billing?.plan || me?.plan || 'free'

  return (
    <div>
      <h2 style={{ fontSize: 18 }} className="mb-8">Settings</h2>

      {msg && (
        <div className={`panel mb-8 ${msg.ok ? '' : 'negative'}`} style={{ fontSize: 13 }}>
          {msg.text}
        </div>
      )}

      <div className="grid-12">
        <div className="panel col-6">
          <div className="panel-header"><span className="panel-title"><Shield size={13} /> Profile</span></div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Email</span>
            <span className="mono">{me?.email || '—'}</span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Name</span>
            <span>{me?.full_name || '—'}</span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Plan</span>
            <span className="badge badge-blue">{plan}</span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Member since</span>
            <span className="mono" style={{ fontSize: 12 }}>
              {me?.created_at ? new Date(me.created_at).toLocaleDateString() : '—'}
            </span>
          </div>
          <button className="btn btn-sm" onClick={logout} style={{ marginTop: 8 }}>
            <LogOut size={13} /> Sign out
          </button>
        </div>

        <div className="panel col-6">
          <div className="panel-header"><span className="panel-title"><CreditCard size={13} /> Billing</span></div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Stripe mode</span>
            <span className={`badge ${status?.stripe_mode === 'none' ? 'badge-neutral' : 'badge-green'}`}>
              {status?.stripe_mode || 'none'}
            </span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Dev upgrade</span>
            <span className={`badge ${status?.dev_upgrade_enabled ? 'badge-green' : 'badge-neutral'}`}>
              {status?.dev_upgrade_enabled ? 'enabled' : 'disabled'}
            </span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Subscription</span>
            <span className="mono" style={{ fontSize: 12 }}>
              {billing?.stripe_subscription_id || 'none'}
            </span>
          </div>
          <div className="flex-between mb-4">
            <span className="muted" style={{ fontSize: 12 }}>Entitlements</span>
            <span style={{ fontSize: 12 }}>
              {(billing?.features || []).map((f: string) => (
                <span key={f} className="badge badge-neutral" style={{ marginRight: 4 }}>{f}</span>
              ))}
              {(billing?.features || []).length === 0 && 'none'}
            </span>
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Dev Plan Switcher</span>
          <span className="badge badge-amber">local testing only</span>
        </div>
        <p className="muted mb-8" style={{ fontSize: 12 }}>
          Instantly change your plan to test feature gating without Stripe. Disabled in production.
        </p>
        <div className="flex gap-8" style={{ flexWrap: 'wrap' }}>
          {plans.map((p: any) => (
            <button
              key={p.id}
              className={`btn btn-sm ${p.id === plan ? 'btn-primary' : ''}`}
              disabled={p.id === plan || busy !== ''}
              onClick={() => doUpgrade(p.id)}
            >
              {busy === p.id ? 'Switching…' : `Switch to ${p.name}`}
            </button>
          ))}
          <button
            className="btn btn-sm"
            disabled={plan === 'free' || busy !== ''}
            onClick={doDowngrade}
          >
            {busy === 'free' ? 'Switching…' : 'Downgrade to Free'}
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header"><span className="panel-title"><Database size={13} /> Environment</span></div>
        <div className="muted" style={{ fontSize: 12 }}>
          Research & simulation platform. Stripe checkout and webhook flows are configured server-side; feature
          gating for paper trading, strategy lab, backtesting and risk engine is plan-based.
        </div>
      </div>
    </div>
  )
}
