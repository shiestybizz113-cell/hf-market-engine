import { useState } from 'react'
import {
  Landmark, Bitcoin, Cpu, Zap, Shield, TrendingUp, AlertTriangle,
  Eye, Target, FileText, RefreshCw, Layers, Brain
} from 'lucide-react'
import { runCapitalAllocation, runCapitalScenarios, runCapitalOptimize } from '../services/api'

const RISK_PROFILES = ['conservative', 'balanced', 'aggressive']
const SCENARIOS = [
  ['base', 'Base'],
  ['btc_m25', 'BTC −25%'],
  ['btc_p25', 'BTC +25%'],
  ['power_p30', 'Power +30%'],
  ['power_m20', 'Power −20%'],
  ['difficulty_p20', 'Difficulty +20%'],
  ['gpu_util_m20', 'GPU util −20%'],
  ['bull', 'Bull'],
  ['stress', 'Stress'],
] as const

const ASIC_MODELS = ['S21 Pro', 'S21', 'S19k Pro']
const GPU_MODELS = ['H100', 'H200', 'B200', 'A100', 'L40S', '4090']

const LANE_META: Record<string, { label: string; color: string; icon: any }> = {
  btc: { label: 'BTC Treasury', color: 'var(--amber)', icon: Bitcoin },
  mining: { label: 'Bitcoin Mining', color: 'var(--positive)', icon: Cpu },
  gpu: { label: 'AI / GPU Compute', color: 'var(--accent)', icon: Zap },
  energy: { label: 'Energy / Storage', color: 'var(--purple)', icon: Zap },
}

const STATE_LABEL: Record<string, string> = {
  observed_live: 'LIVE OBSERVED',
  user_assumption: 'ASSUMPTION',
  simulation: 'SIMULATION',
  unavailable: 'UNAVAILABLE',
}

const fmtUsd = (n: number | null | undefined) =>
  n == null || isNaN(n as number) ? '—' : `$${(n as number).toLocaleString(undefined, { maximumFractionDigits: 0 })}`

const fmtNum = (n: number | null | undefined, d = 2) =>
  n == null || isNaN(n as number) ? '—' : (n as number).toLocaleString(undefined, { maximumFractionDigits: d })

function stateBadge(state: string) {
  const cls = state === 'observed_live' ? 'badge-green'
    : state === 'simulation' ? 'badge-amber'
    : state === 'user_assumption' ? 'badge-blue'
    : 'badge-neutral'
  return <span className={`badge ${cls}`}>{STATE_LABEL[state] || state}</span>
}

export default function Capital() {
  const [form, setForm] = useState({
    capital_usd: 1000000,
    available_mw: 1.0,
    horizon_months: 12,
    electricity_usd_kwh: 0.05,
    risk_profile: 'balanced',
    asic_model: 'S21 Pro',
    btc_price_at_horizon: 80000,
    gpu_model: 'H100',
    gpu_rental_usd_per_hr: 2.0,
    gpu_units_cap: 64,
    energy_sell_price_usd_kwh: 0.09,
    energy_acquisition_usd_kwh: 0.035,
    storage_mwh: 5,
    storage_capex_usd_per_mwh: 120000,
  })
  const [tab, setTab] = useState<'run' | 'scenarios' | 'optimize'>('run')
  const [run, setRun] = useState<any>(null)
  const [matrix, setMatrix] = useState<any>(null)
  const [optimize, setOptimize] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [drawer, setDrawer] = useState<any>(null)

  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.type === 'number' ? parseFloat(e.target.value) : e.target.value })

  async function doRun() {
    setLoading(true); setError(null)
    try {
      const r = await runCapitalAllocation(form)
      setRun(r.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Run failed')
    } finally { setLoading(false) }
  }

  async function doScenarios() {
    setLoading(true); setError(null)
    try {
      const r = await runCapitalScenarios({ run: form, vectors: SCENARIOS.map(s => s[0]) })
      setMatrix(r.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Scenario run failed')
    } finally { setLoading(false) }
  }

  async function doOptimize() {
    setLoading(true); setError(null)
    try {
      const r = await runCapitalOptimize({
        capital_usd: form.capital_usd,
        available_mw: form.available_mw,
        horizon_months: form.horizon_months,
        electricity_usd_kwh: form.electricity_usd_kwh,
        asic_model: form.asic_model,
        risk_profiles: RISK_PROFILES,
      })
      setOptimize(r.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Optimize failed')
    } finally { setLoading(false) }
  }

  function exec() {
    if (tab === 'run') doRun()
    else if (tab === 'scenarios') doScenarios()
    else doOptimize()
  }

  const numIn = (label: string, key: string, step = 0.01) => (
    <div className="form-row">
      <label>{label}</label>
      <input type="number" step={step} value={form[key as keyof typeof form] as number} onChange={set(key)} />
    </div>
  )
  const selIn = (label: string, key: string, options: readonly string[]) => (
    <div className="form-row">
      <label>{label}</label>
      <select value={form[key as keyof typeof form] as string} onChange={set(key)}>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )

  return (
    <div>
      <div className="mb-8 flex-between">
        <div>
          <h2 style={{ fontSize: 18 }}>Capital Allocation Command Center</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            One economic frame across four lanes — BTC treasury, mining, AI/GPU compute, energy/storage.
            The optimizer <b>proposes only</b>; it never trades, spends or deploys capital.
          </p>
        </div>
        <button className="btn btn-primary" onClick={exec} disabled={loading}>
          {loading ? <RefreshCw size={13} className="spin" /> : <Target size={13} />} Run
        </button>
      </div>

      {error && (
        <div className="panel mb-8" style={{ borderColor: 'var(--negative)' }}>
          <div className="flex gap-8" style={{ alignItems: 'center' }}>
            <AlertTriangle size={14} className="negative" />
            <span style={{ fontSize: 12 }}>{error}</span>
          </div>
        </div>
      )}

      {/* Inputs */}
      <div className="panel mb-8">
        <div className="panel-header">
          <span className="panel-title"><Layers size={14} /> Scenario inputs</span>
          <div className="flex gap-8">
            {(['run', 'scenarios', 'optimize'] as const).map(t => (
              <button key={t} className={`btn btn-sm ${tab === t ? 'btn-primary' : ''}`} onClick={() => setTab(t)}>
                {t === 'run' ? 'Evaluate' : t === 'scenarios' ? 'Scenario matrix' : 'Optimize'}
              </button>
            ))}
          </div>
        </div>
        <div className="grid-12" style={{ marginTop: 12 }}>
          <div className="col-3">{numIn('Capital ($)', 'capital_usd', 10000)}</div>
          <div className="col-3">{numIn('Power (MW)', 'available_mw', 0.1)}</div>
          <div className="col-3">{numIn('Horizon (months)', 'horizon_months', 1)}</div>
          <div className="col-3">{selIn('Risk profile', 'risk_profile', RISK_PROFILES)}</div>
          <div className="col-3">{numIn('Electricity ($/kWh)', 'electricity_usd_kwh', 0.01)}</div>
          <div className="col-3">{selIn('ASIC model', 'asic_model', ASIC_MODELS)}</div>
          <div className="col-3">{numIn('BTC @ horizon ($)', 'btc_price_at_horizon', 1000)}</div>
          <div className="col-3">{selIn('GPU model', 'gpu_model', GPU_MODELS)}</div>
          <div className="col-3">{numIn('GPU achieved rent ($/hr)', 'gpu_rental_usd_per_hr', 0.1)}</div>
          <div className="col-3">{numIn('GPU units cap', 'gpu_units_cap', 1)}</div>
          <div className="col-3">{numIn('Energy sell ($/kWh)', 'energy_sell_price_usd_kwh', 0.01)}</div>
          <div className="col-3">{numIn('Energy acquisition ($/kWh)', 'energy_acquisition_usd_kwh', 0.01)}</div>
          <div className="col-3">{numIn('Storage (MWh)', 'storage_mwh', 1)}</div>
          <div className="col-3">{numIn('Storage capex ($/MWh)', 'storage_capex_usd_per_mwh', 10000)}</div>
        </div>
      </div>

      {/* Run result */}
      {tab === 'run' && run && (
        <CapitalRunView run={run} onDrawer={setDrawer} />
      )}

      {/* Scenario matrix */}
      {tab === 'scenarios' && matrix && (
        <div className="panel mb-8">
          <div className="panel-header">
            <span className="panel-title">Scenario matrix</span>
            <span className="badge badge-amber">{matrix.matrix.length} vectors</span>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Scenario</th>
                  <th>BTC treasury<br /><span className="muted">horizon value</span></th>
                  <th>Mining<br /><span className="muted">horizon value</span></th>
                  <th>GPU<br /><span className="muted">profit/mo</span></th>
                  <th>Energy<br /><span className="muted">profit/mo</span></th>
                </tr>
              </thead>
              <tbody>
                {matrix.matrix.map((m: any) => (
                  <tr key={m.label}>
                    <td className="mono">{m.label}</td>
                    <td>{fmtUsd(m.lanes.btc?.horizon_value)}</td>
                    <td>{fmtUsd(m.lanes.mining?.horizon_value)}</td>
                    <td>{fmtUsd(m.lanes.gpu?.operating_profit_month)}</td>
                    <td>{fmtUsd(m.lanes.energy?.operating_profit_month)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Optimize result */}
      {tab === 'optimize' && optimize && (
        <div className="panel mb-8">
          <div className="panel-header">
            <span className="panel-title">Optimizer proposals</span>
            <span className="badge badge-amber">Proposal only</span>
          </div>
          <div className="grid-12">
            {Object.entries(optimize.proposals).map(([profile, p]: [string, any]) => (
              <div key={profile} className="panel col-4" style={{ background: 'var(--bg)' }}>
                <div className="panel-header">
                  <span className="panel-title" style={{ textTransform: 'capitalize' }}>{profile}</span>
                </div>
                <table className="table">
                  <tbody>
                    {Object.entries(p.proposed_pct as Record<string, number>).map(([k, v]) => (
                      <tr key={k}>
                        <td className="muted">{k.replace(/_/g, ' ')}</td>
                        <td className="text-right mono">{v}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
                  reserve {p.reserve_pct}% · treasury floor {p.treasury_floor_pct}%
                </div>
              </div>
            ))}
          </div>
          <p className="muted mt-8" style={{ fontSize: 11 }}>{optimize.disclaimer}</p>
        </div>
      )}

      {/* Proof drawer */}
      {drawer && (
        <div className="panel mb-8" style={{ borderColor: 'var(--accent)' }}>
          <div className="panel-header">
            <span className="panel-title"><Eye size={14} /> Evidence receipt</span>
            <button className="btn btn-sm" onClick={() => setDrawer(null)}>Close</button>
          </div>
          <pre style={{ fontSize: 11, lineHeight: 1.5, overflow: 'auto', maxHeight: 320, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(drawer, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

function CapitalRunView({ run, onDrawer }: { run: any; onDrawer: (d: any) => void }) {
  const lanes = run.lanes
  const rec = run.recommendation

  return (
    <div>
      {/* Header metrics */}
      <div className="grid-12 mb-8">
        <div className="panel col-4">
          <div className="panel-header"><span className="panel-title"><Target size={14} /> Ranking basis</span></div>
          <p className="muted" style={{ fontSize: 11, lineHeight: 1.5 }}>{run.ranking_basis}</p>
        </div>
        <div className="panel col-4">
          <div className="panel-header"><span className="panel-title"><TrendingUp size={14} /> Lane ranking</span></div>
          <div className="flex gap-8" style={{ flexWrap: 'wrap' }}>
            {run.ranking.map((k: string, i: number) => (
              <span key={k} className="badge badge-blue">#{i + 1} {LANE_META[k]?.label || k}</span>
            ))}
          </div>
        </div>
        <div className="panel col-4">
          <div className="panel-header"><span className="panel-title"><Shield size={14} /> Evidence</span></div>
          <div style={{ fontSize: 12 }}>
            BTC {fmtUsd(run.observed.btc_price)} <span className="muted">({run.observed.btc_price_provider})</span>
            <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
              {stateBadge('observed_live')} live · GPU/energy are assumptions
            </div>
          </div>
        </div>
      </div>

      {/* Four lanes */}
      <div className="grid-12 mb-8">
        {(['btc', 'mining', 'gpu', 'energy'] as const).map(key => {
          const lane = lanes[key]
          const meta = LANE_META[key]
          const Icon = meta.icon
          return (
            <div key={key} className="panel col-3" style={{ borderColor: lane.available ? 'var(--border)' : 'var(--border)' }}>
              <div className="panel-header">
                <span className="panel-title flex gap-8" style={{ alignItems: 'center' }}>
                  <Icon size={13} style={{ color: meta.color }} /> {meta.label}
                </span>
                {stateBadge(lane.evidence_state)}
              </div>
              {!lane.available ? (
                <div className="muted" style={{ fontSize: 12 }}>
                  <div style={{ marginBottom: 4 }}><AlertTriangle size={12} className="amber" /> Unavailable</div>
                  <div style={{ fontSize: 11 }}>{lane.reason}</div>
                </div>
              ) : (
                <div style={{ fontSize: 12 }}>
                  <div className="flex-between mb-8">
                    <span className="muted">Monthly flow</span>
                    <span className={lane.operating_profit_month >= 0 ? 'positive mono' : 'negative mono'}>
                      {fmtUsd(lane.operating_profit_month)}
                    </span>
                  </div>
                  <div className="flex-between mb-8">
                    <span className="muted">Capital</span>
                    <span className="mono">{fmtUsd(lane.capital_allocated)}</span>
                  </div>
                  <div className="flex-between mb-8">
                    <span className="muted">Horizon value</span>
                    <span className="mono">{fmtUsd(lane.horizon_value)}</span>
                  </div>
                  <div className="flex-between mb-8">
                    <span className="muted">Units</span>
                    <span className="mono">{lane.units == null ? '—' : fmtNum(lane.units, 0)}</span>
                  </div>
                  {lane.profit_per_mw != null && (
                    <div className="flex-between mb-8">
                      <span className="muted">$/MW/mo</span>
                      <span className="mono">{fmtUsd(lane.profit_per_mw)}</span>
                    </div>
                  )}
                  {lane.simple_payback_days != null && (
                    <div className="flex-between mb-8">
                      <span className="muted">Payback</span>
                      <span className="mono">{Math.round(lane.simple_payback_days)}d</span>
                    </div>
                  )}
                  <div className="flex" style={{ flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                    {lane.risk_flags?.map((f: string) => <span key={f} className="badge badge-red" style={{ fontSize: 9 }}>{f}</span>)}
                  </div>
                </div>
              )}
              <button className="btn btn-sm mt-8" onClick={() => onDrawer({ ...lane, ...(lane.evidence || {}) })}>
                <FileText size={11} /> Proof
              </button>
            </div>
          )
        })}
      </div>

      {/* Proposal + AI council */}
      <div className="grid-12">
        <div className="panel col-5">
          <div className="panel-header">
            <span className="panel-title"><Target size={14} /> Proposed allocation</span>
            <span className="badge badge-amber">Proposal only</span>
          </div>
          <table className="table">
            <tbody>
              {Object.entries(rec.proposed_pct as Record<string, number>).map(([k, v]) => (
                <tr key={k}>
                  <td className="muted">{k.replace(/_/g, ' ')}</td>
                  <td className="text-right mono">{v}%</td>
                  <td className="text-right mono">{fmtUsd(rec.proposed_usd[k])}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 11, marginTop: 8 }}>{rec.basis}</p>
          <p className="muted" style={{ fontSize: 11 }}>{rec.disclaimer}</p>
        </div>
        <div className="panel col-7" style={{ borderColor: 'var(--purple)' }}>
          <div className="panel-header">
            <span className="panel-title flex gap-8" style={{ alignItems: 'center' }}>
              <Brain size={14} /> AI Capital Council
            </span>
            <span className="badge badge-blue">Review</span>
          </div>
          <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{run.ai_review}</p>
          <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
            Receipt <span className="mono">{run.receipt_id}</span>
          </div>
          <button className="btn btn-sm mt-8" onClick={() => onDrawer(run)}>
            <FileText size={11} /> Full run proof
          </button>
        </div>
      </div>
    </div>
  )
}
