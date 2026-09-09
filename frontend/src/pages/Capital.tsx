import { useEffect, useState, type ChangeEvent } from 'react'
import {
  Activity, AlertTriangle, Bitcoin, Box, Brain, Cpu, Database, Eye,
  FileText, Landmark, Layers, LockKeyhole, Plus, RefreshCw, Server, Target,
  TrendingUp, X, Zap,
} from 'lucide-react'
import {
  createAsset, getAssetSummary, getAssets, getBillingMe, getComputeOffers,
  getEnergyPrices, getEvidenceGraph, getHardwareOffers, retireAsset,
  runCapitalAllocation, runCapitalOptimize, runCapitalScenarios,
} from '../services/api'

const RISK_PROFILES = ['conservative', 'balanced', 'aggressive']
const SCENARIOS = [
  ['base', 'Base'], ['btc_m25', 'BTC −25%'], ['btc_p25', 'BTC +25%'],
  ['power_p30', 'Power +30%'], ['power_m20', 'Power −20%'],
  ['difficulty_p20', 'Difficulty +20%'], ['gpu_util_m20', 'GPU util −20%'],
  ['bull', 'Bull'], ['stress', 'Stress'],
] as const
const ASIC_MODELS = ['S21 Pro', 'S21', 'S19k Pro', 'S19 Pro', 'M60S', 'M66S', 'A1566', 'A1366', 'Bitaxe Max']
const GPU_MODELS = ['H100', 'H200', 'B200', 'A100', 'L40S', '4090']

const LANE_META: Record<string, { label: string; icon: any }> = {
  btc: { label: 'BTC Treasury', icon: Bitcoin },
  mining: { label: 'Bitcoin Mining', icon: Cpu },
  gpu: { label: 'AI / GPU Compute', icon: Server },
  energy: { label: 'Energy / Storage', icon: Zap },
}

const STATE_LABEL: Record<string, string> = {
  observed_live: 'LIVE OBSERVED', user_assumption: 'ASSUMPTION',
  simulation: 'SIMULATION', unavailable: 'UNAVAILABLE',
}

const fmtUsd = (n: any, digits = 0) => n == null || Number.isNaN(Number(n))
  ? '—' : `$${Number(n).toLocaleString(undefined, { maximumFractionDigits: digits })}`
const fmtNum = (n: any, digits = 2) => n == null || Number.isNaN(Number(n))
  ? '—' : Number(n).toLocaleString(undefined, { maximumFractionDigits: digits })

function stateBadge(state?: string) {
  const value = state || 'unavailable'
  const cls = value === 'observed_live' ? 'badge-green'
    : value === 'simulation' ? 'badge-amber'
      : value === 'user_assumption' ? 'badge-blue' : 'badge-neutral'
  return <span className={`badge ${cls}`}>{STATE_LABEL[value] || value}</span>
}

function qualityBadge(label?: string, score?: number) {
  const value = label || 'UNAVAILABLE'
  const cls = value === 'COMPLETE' ? 'badge-green'
    : value === 'PARTIAL' ? 'badge-blue'
      : value === 'CONFLICTING' || value === 'STALE' ? 'badge-amber' : 'badge-red'
  return <span className={`badge ${cls}`}>{value}{score != null ? ` · ${score}%` : ''}</span>
}

function newestOffer(rows: any[] = []) {
  return rows.find(r => r.fresh && r.state === 'observed_live')
    || rows.find(r => r.fresh)
    || rows[0]
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
    gpu_utilization_pct: 85,
    gpu_uptime_pct: 100,
    gpu_pue: 1.3,
    energy_sell_price_usd_kwh: 0.09,
    energy_acquisition_usd_kwh: 0.035,
    energy_utilization_pct: 100,
    storage_mwh: 5,
    storage_capex_usd_per_mwh: 120000,
    storage_roundtrip_pct: 85,
    pool_fee_pct: 1,
    uptime_pct: 95,
    difficulty_growth_pct_year: 20,
    cash_interest_rate_pct_year: 4,
  })
  const [tab, setTab] = useState<'run' | 'scenarios' | 'optimize'>('run')
  const [run, setRun] = useState<any>(null)
  const [matrix, setMatrix] = useState<any>(null)
  const [optimize, setOptimize] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [proof, setProof] = useState<any>(null)
  const [infra, setInfra] = useState<any>({ hardware: null, compute: null, energy: null })
  const [assets, setAssets] = useState<any[]>([])
  const [owned, setOwned] = useState<any>(null)
  const [fleetEntitled, setFleetEntitled] = useState(false)
  const [planName, setPlanName] = useState('')
  const [assetOpen, setAssetOpen] = useState(false)
  const [assetForm, setAssetForm] = useState<any>({ asset_type: 'asic', subject: 'S21 Pro', units: 1, value_usd: 0 })

  const set = (key: string) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const value = e.target.type === 'number' ? Number(e.target.value) : e.target.value
    setForm(prev => ({ ...prev, [key]: value }))
  }

  async function loadInfra() {
    const settled = await Promise.allSettled([
      getHardwareOffers(), getComputeOffers(), getEnergyPrices(), getBillingMe(),
    ])
    const value = (i: number) => settled[i].status === 'fulfilled'
      ? (settled[i] as PromiseFulfilledResult<any>).value.data : null

    setInfra({ hardware: value(0), compute: value(1), energy: value(2) })
    const billing = value(3)
    const entitled = Boolean(billing?.features?.includes('mining_fleet'))
    setFleetEntitled(entitled)
    setPlanName(billing?.plan_name || billing?.plan || '')

    if (!entitled) {
      setAssets([])
      setOwned(null)
      setAssetOpen(false)
      return
    }

    const fleet = await Promise.allSettled([getAssets(), getAssetSummary()])
    const assetsResult = fleet[0].status === 'fulfilled' ? fleet[0].value.data : null
    const summaryResult = fleet[1].status === 'fulfilled' ? fleet[1].value.data : null
    setAssets(assetsResult?.assets || [])
    setOwned(summaryResult || null)
  }

  useEffect(() => { void loadInfra() }, [])

  async function execute() {
    setLoading(true); setError(null)
    try {
      if (tab === 'run') {
        const r = await runCapitalAllocation(form)
        setRun(r.data)
      } else if (tab === 'scenarios') {
        const r = await runCapitalScenarios({ run: form, vectors: SCENARIOS.map(s => s[0]) })
        setMatrix(r.data)
      } else {
        const r = await runCapitalOptimize({ ...form, risk_profiles: RISK_PROFILES })
        setOptimize(r.data)
      }
      await loadInfra()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Capital request failed')
    } finally { setLoading(false) }
  }

  async function openProof(receiptId?: string, lane?: string) {
    if (!receiptId) return
    try {
      const r = await getEvidenceGraph(receiptId)
      setProof({ ...r.data, focus_lane: lane })
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Proof graph unavailable')
    }
  }

  async function addAsset() {
    if (!fleetEntitled) return
    setError(null)
    try {
      await createAsset(assetForm)
      setAssetOpen(false)
      setAssetForm({ asset_type: 'asic', subject: 'S21 Pro', units: 1, value_usd: 0 })
      await loadInfra()
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Could not add asset')
    }
  }

  async function retire(id: string) {
    if (!fleetEntitled) return
    try { await retireAsset(id); await loadInfra() }
    catch (err: any) { setError(err.response?.data?.detail || 'Could not retire asset') }
  }

  const numIn = (label: string, key: string, step = 0.01) => (
    <div className="form-row"><label>{label}</label>
      <input type="number" step={step} value={(form as any)[key]} onChange={set(key)} />
    </div>
  )
  const selIn = (label: string, key: string, options: readonly string[]) => (
    <div className="form-row"><label>{label}</label>
      <select value={(form as any)[key]} onChange={set(key)}>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )

  return (
    <div>
      <div className="mb-8 flex-between">
        <div>
          <div className="flex gap-8" style={{ alignItems: 'center' }}>
            <Landmark size={18} /><h2 style={{ fontSize: 18 }}>Capital Allocation Command Center</h2>
            <span className="badge badge-blue">V2 EVIDENCE FABRIC</span>
          </div>
          <p className="muted" style={{ fontSize: 12, maxWidth: 900 }}>
            Markets + mining + compute + energy on one capital frame. Advanced+ can include persistent owned-fleet state.
            Evidence before recommendation. Optimizer proposes only; there is no trade, spend, or deployment action here.
          </p>
        </div>
        <div className="flex gap-8">
          <button className="btn" onClick={() => void loadInfra()}><RefreshCw size={13} /> Refresh data</button>
          <button className="btn btn-primary" onClick={() => void execute()} disabled={loading}>
            {loading ? <RefreshCw size={13} className="spin" /> : <Target size={13} />} Run
          </button>
        </div>
      </div>

      {error && <div className="panel mb-8" style={{ borderColor: 'var(--negative)' }}>
        <div className="flex gap-8" style={{ alignItems: 'center' }}><AlertTriangle size={14} className="negative" /><span>{String(error)}</span></div>
      </div>}

      <ProviderStrip infra={infra} />
      <OwnedAssets assets={assets} owned={owned} entitled={fleetEntitled} planName={planName}
        assetOpen={assetOpen} setAssetOpen={setAssetOpen} assetForm={assetForm} setAssetForm={setAssetForm}
        addAsset={addAsset} retire={retire} />

      <div className="panel mb-8">
        <div className="panel-header">
          <span className="panel-title"><Layers size={14} /> Capital scenario</span>
          <div className="flex gap-8">
            {(['run', 'scenarios', 'optimize'] as const).map(t => <button key={t}
              className={`btn btn-sm ${tab === t ? 'btn-primary' : ''}`} onClick={() => setTab(t)}>
              {t === 'run' ? 'Evaluate' : t === 'scenarios' ? 'Scenario matrix' : 'Optimize'}
            </button>)}
          </div>
        </div>
        <div className="grid-12" style={{ marginTop: 12 }}>
          <div className="col-3">{numIn('New capital ($)', 'capital_usd', 10000)}</div>
          <div className="col-3">{numIn('New / unregistered power (MW)', 'available_mw', .1)}</div>
          <div className="col-3">{numIn('Horizon (months)', 'horizon_months', 1)}</div>
          <div className="col-3">{selIn('Risk profile', 'risk_profile', RISK_PROFILES)}</div>
          <div className="col-3">{numIn('Delivered electricity ($/kWh)', 'electricity_usd_kwh', .005)}</div>
          <div className="col-3">{selIn('ASIC model', 'asic_model', ASIC_MODELS)}</div>
          <div className="col-3">{numIn('BTC @ horizon ($)', 'btc_price_at_horizon', 1000)}</div>
          <div className="col-3">{numIn('Difficulty growth (%/yr)', 'difficulty_growth_pct_year', 1)}</div>
          <div className="col-3">{selIn('GPU model', 'gpu_model', GPU_MODELS)}</div>
          <div className="col-3">{numIn('GPU achieved revenue ($/hr)', 'gpu_rental_usd_per_hr', .1)}</div>
          <div className="col-3">{numIn('GPU utilization (%)', 'gpu_utilization_pct', 1)}</div>
          <div className="col-3">{numIn('GPU units cap', 'gpu_units_cap', 1)}</div>
          <div className="col-3">{numIn('Energy acquisition ($/kWh)', 'energy_acquisition_usd_kwh', .005)}</div>
          <div className="col-3">{numIn('Energy sell / avoided cost ($/kWh)', 'energy_sell_price_usd_kwh', .005)}</div>
          <div className="col-3">{numIn('New storage (MWh)', 'storage_mwh', 1)}</div>
          <div className="col-3">{numIn('Storage capex ($/MWh)', 'storage_capex_usd_per_mwh', 10000)}</div>
        </div>
      </div>

      {tab === 'run' && run && <CapitalRunView run={run} openProof={openProof} />}
      {tab === 'scenarios' && matrix && <ScenarioView matrix={matrix} openProof={openProof} />}
      {tab === 'optimize' && optimize && <OptimizeView optimize={optimize} openProof={openProof} />}
      {proof && <ProofDrawer proof={proof} close={() => setProof(null)} />}
    </div>
  )
}

function ProviderStrip({ infra }: { infra: any }) {
  const cards = [
    { key: 'hardware', label: 'ASIC market', icon: Cpu, rows: infra.hardware?.offers || [] },
    { key: 'compute', label: 'GPU compute', icon: Server, rows: infra.compute?.offers || [] },
    { key: 'energy', label: 'Energy market', icon: Zap, rows: infra.energy?.prices || [] },
  ]
  return <div className="grid-12 mb-8">
    {cards.map(c => {
      const current = newestOffer(c.rows)
      const Icon = c.icon
      return <div className="panel col-4" key={c.key}>
        <div className="panel-header"><span className="panel-title"><Icon size={13} /> {c.label}</span>{stateBadge(current?.state)}</div>
        <div className="flex-between"><span className="muted">Candidates</span><span className="mono">{c.rows.length}</span></div>
        <div className="flex-between mt-8"><span className="muted">Provider</span><span className="mono">{current?.provider || 'not configured'}</span></div>
        <div className="muted mt-8" style={{ fontSize: 10 }}>
          {current ? `${current.fresh ? 'fresh' : 'stale'} · age ${fmtNum(current.age_seconds, 0)}s` : 'No observed feed; engine remains assumption/unavailable as appropriate.'}
        </div>
      </div>
    })}
  </div>
}

function OwnedAssets({ assets, owned, entitled, planName, assetOpen, setAssetOpen, assetForm, setAssetForm, addAsset, retire }: any) {
  const assetType = assetForm.asset_type
  const change = (k: string) => (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setAssetForm((p: any) => ({ ...p, [k]: e.target.type === 'number' ? Number(e.target.value) : e.target.value }))

  if (!entitled) {
    return <div className="panel mb-8" style={{ borderColor: 'var(--amber)' }}>
      <div className="panel-header">
        <span className="panel-title"><LockKeyhole size={14} /> Persistent owned-fleet modeling</span>
        <span className="badge badge-amber">ADVANCED+</span>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        Your {planName || 'current'} plan can run Capital Allocation now. Advanced+ adds persistent ASIC/GPU/power/storage/treasury inventory so the optimizer accounts for assets you already own before proposing new capital.
      </p>
    </div>
  }

  return <div className="panel mb-8">
    <div className="panel-header">
      <span className="panel-title"><Box size={14} /> Owned assets / fleet baseline</span>
      <button className="btn btn-sm" onClick={() => setAssetOpen(!assetOpen)}>{assetOpen ? <X size={12} /> : <Plus size={12} />} {assetOpen ? 'Close' : 'Add asset'}</button>
    </div>
    <div className="grid-12" style={{ marginTop: 10 }}>
      <MiniMetric label="Assets" value={owned?.asset_count ?? assets.length} />
      <MiniMetric label="ASICs" value={owned?.asics?.units || 0} />
      <MiniMetric label="GPUs" value={owned?.gpus?.units || 0} />
      <MiniMetric label="Owned power" value={`${fmtNum(owned?.power_mw || 0, 2)} MW`} />
      <MiniMetric label="Storage" value={`${fmtNum(owned?.storage_mwh || 0, 2)} MWh`} />
      <MiniMetric label="BTC treasury" value={`${fmtNum(owned?.treasury_btc || 0, 4)} BTC`} />
    </div>

    {assets.length > 0 && <div className="table-wrap mt-8"><table className="table"><thead><tr>
      <th>Asset</th><th>Type</th><th>Units</th><th>Value</th><th>Status</th><th>Evidence</th><th></th>
    </tr></thead><tbody>{assets.slice(0, 8).map((a: any) => <tr key={a.asset_id}>
      <td>{a.name || a.subject}</td><td className="mono">{a.asset_type}</td><td>{a.units}</td><td>{fmtUsd(a.value_usd)}</td>
      <td>{a.status}</td><td className="mono" style={{ fontSize: 9 }}>{a.evidence_id?.slice(0, 8) || '—'}</td>
      <td>{a.status === 'active' && <button className="btn btn-sm" onClick={() => retire(a.asset_id)}>Retire</button>}</td>
    </tr>)}</tbody></table></div>}

    {assetOpen && <div className="grid-12 mt-8" style={{ borderTop: '1px solid var(--border)', paddingTop: 10 }}>
      <div className="col-2 form-row"><label>Type</label><select value={assetType} onChange={change('asset_type')}>
        {['asic', 'gpu', 'power', 'storage', 'treasury'].map(x => <option key={x}>{x}</option>)}
      </select></div>
      <div className="col-2 form-row"><label>Name / model</label><input value={assetForm.subject || ''} onChange={change('subject')} /></div>
      <div className="col-2 form-row"><label>Units</label><input type="number" min="1" value={assetForm.units || 1} onChange={change('units')} /></div>
      <div className="col-2 form-row"><label>Current value ($)</label><input type="number" value={assetForm.value_usd || 0} onChange={change('value_usd')} /></div>
      {assetType === 'asic' && <><div className="col-2 form-row"><label>TH/s per unit</label><input type="number" onChange={change('hashrate_ths_per_unit')} /></div><div className="col-2 form-row"><label>kW per unit</label><input type="number" step=".01" onChange={change('power_kw_per_unit')} /></div></>}
      {assetType === 'gpu' && <div className="col-2 form-row"><label>kW per GPU</label><input type="number" step=".01" onChange={change('power_kw_per_unit')} /></div>}
      {assetType === 'power' && <div className="col-2 form-row"><label>Power (MW)</label><input type="number" step=".1" onChange={change('power_mw')} /></div>}
      {assetType === 'storage' && <div className="col-2 form-row"><label>Storage (MWh)</label><input type="number" step="1" onChange={change('storage_mwh')} /></div>}
      {assetType === 'treasury' && <div className="col-2 form-row"><label>BTC quantity</label><input type="number" step=".001" onChange={change('btc_qty')} /></div>}
      <div className="col-2" style={{ alignSelf: 'end' }}><button className="btn btn-primary" onClick={addAsset}><Plus size={12} /> Add</button></div>
    </div>}
  </div>
}

function MiniMetric({ label, value }: { label: string; value: any }) {
  return <div className="col-2"><div className="muted" style={{ fontSize: 10 }}>{label}</div><div className="mono" style={{ fontSize: 15, marginTop: 3 }}>{value}</div></div>
}

function CapitalRunView({ run, openProof }: { run: any; openProof: (id?: string, lane?: string) => void }) {
  const quality = run.evidence?.quality || {}
  return <>
    <div className="panel mb-8">
      <div className="panel-header"><span className="panel-title"><Activity size={14} /> Evidence state</span>
        <button className="btn btn-sm" onClick={() => openProof(run.receipt_id)}><Eye size={11} /> Full proof graph</button>
      </div>
      <div className="grid-12">
        <MiniMetric label="Observed" value={`${quality.overall_observed_pct ?? 0}%`} />
        <MiniMetric label="Assumption / simulation" value={`${quality.overall_assumption_pct ?? 0}%`} />
        <MiniMetric label="Conflicts" value={quality.conflict_count ?? 0} />
        <MiniMetric label="Stale" value={quality.stale_count ?? 0} />
        <MiniMetric label="Missing" value={quality.missing_count ?? 0} />
        <MiniMetric label="Receipt" value={run.receipt_id?.slice(0, 8) || '—'} />
      </div>
    </div>

    <div className="grid-12 mb-8">
      {(['btc', 'mining', 'gpu', 'energy'] as const).map(key => <LaneCard key={key} lane={run.lanes[key]}
        laneKey={key} receiptId={run.receipt_id} openProof={openProof} />)}
    </div>

    <div className="grid-12 mb-8">
      <div className="panel col-5"><div className="panel-header"><span className="panel-title"><Target size={14} /> Proposed allocation</span>
        {qualityBadge(run.recommendation?.evidence?.label === 'EVIDENCE_BACKED' ? 'COMPLETE' : 'PARTIAL')}
      </div><table className="table"><tbody>
        {Object.entries(run.recommendation?.proposed_pct || {}).map(([k, v]: any) => <tr key={k}><td className="muted">{k.replace(/_/g, ' ')}</td><td className="text-right mono">{v}%</td><td className="text-right mono">{fmtUsd(run.recommendation.proposed_usd?.[k])}</td></tr>)}
      </tbody></table><p className="muted mt-8" style={{ fontSize: 11 }}>{run.recommendation?.basis}</p></div>

      <div className="panel col-7" style={{ borderColor: 'var(--purple)' }}><div className="panel-header"><span className="panel-title"><Brain size={14} /> AI Capital Council</span><span className="badge badge-blue">EVIDENCE-BOUND</span></div>
        <p style={{ fontSize: 13, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{run.ai_review || 'AI review not consumed for this run. Deterministic economics and evidence receipt are still available.'}</p>
        <div className="muted" style={{ fontSize: 10 }}>Receipt <span className="mono">{run.receipt_id}</span></div>
      </div>
    </div>
  </>
}

function LaneCard({ lane, laneKey, receiptId, openProof }: any) {
  const meta = LANE_META[laneKey]
  const Icon = meta.icon
  const q = lane?.evidence_quality || {}
  if (!lane) return null
  const metric = (label: string, value: any) => <button onClick={() => openProof(receiptId, laneKey)}
    style={{ width: '100%', border: 0, padding: '4px 0', background: 'transparent', color: 'inherit', cursor: 'pointer' }}>
    <div className="flex-between"><span className="muted">{label}</span><span className="mono">{value}</span></div>
  </button>
  return <div className="panel col-3">
    <div className="panel-header"><span className="panel-title"><Icon size={13} /> {meta.label}</span>{stateBadge(lane.evidence_state)}</div>
    <div className="mb-8">{qualityBadge(q.label, q.score)}</div>
    {!lane.available ? <div className="muted"><AlertTriangle size={12} /> {lane.reason}</div> : <>
      {metric('Monthly flow', fmtUsd(lane.operating_profit_month))}
      {metric('Capital deployed', fmtUsd(lane.capital_allocated))}
      {metric('Horizon value', fmtUsd(lane.horizon_value))}
      {metric('Power', lane.power_mw != null ? `${fmtNum(lane.power_mw, 3)} MW` : '—')}
      {metric('Units', lane.units == null ? '—' : fmtNum(lane.units, 2))}
      {lane.profit_per_mw != null && metric('Profit / MW / mo', fmtUsd(lane.profit_per_mw))}
      {lane.simple_payback_days != null && metric('Simple payback', `${fmtNum(lane.simple_payback_days, 0)}d`)}
    </>}
    <div className="flex gap-8 mt-8" style={{ flexWrap: 'wrap' }}>
      <span className="badge badge-blue">{q.observed_pct ?? 0}% observed</span><span className="badge badge-neutral">{q.assumption_pct ?? 0}% assumed</span>
      {(q.conflicts || 0) > 0 && <span className="badge badge-amber">{q.conflicts} conflict</span>}
      {(q.stale || 0) > 0 && <span className="badge badge-amber">{q.stale} stale</span>}
    </div>
    {lane.risk_flags?.length > 0 && <div className="flex mt-8" style={{ flexWrap: 'wrap', gap: 4 }}>{lane.risk_flags.map((f: string) => <span key={f} className="badge badge-red" style={{ fontSize: 9 }}>{f}</span>)}</div>}
    <button className="btn btn-sm mt-8" onClick={() => openProof(receiptId, laneKey)}><FileText size={11} /> Proof</button>
  </div>
}

function ScenarioView({ matrix, openProof }: any) {
  return <div className="panel mb-8"><div className="panel-header"><span className="panel-title"><TrendingUp size={14} /> Fleet-aware scenario matrix</span>
    <button className="btn btn-sm" onClick={() => openProof(matrix.receipt_id)}><Eye size={11} /> Proof</button></div>
    <div className="table-wrap"><table className="table"><thead><tr><th>Scenario</th><th>BTC horizon</th><th>Mining / mo</th><th>GPU / mo</th><th>Energy / mo</th><th>Fleet</th></tr></thead><tbody>
      {matrix.matrix.map((m: any) => <tr key={m.label}><td>{m.label}</td><td>{fmtUsd(m.lanes.btc?.horizon_value)}</td><td>{fmtUsd(m.lanes.mining?.operating_profit_month)}</td><td>{fmtUsd(m.lanes.gpu?.operating_profit_month)}</td><td>{fmtUsd(m.lanes.energy?.operating_profit_month)}</td><td>{m.owned_fleet_accounted ? 'included' : '—'}</td></tr>)}
    </tbody></table></div><p className="muted mt-8" style={{ fontSize: 10 }}>{matrix.disclaimer}</p>
  </div>
}

function OptimizeView({ optimize, openProof }: any) {
  return <div className="panel mb-8"><div className="panel-header"><span className="panel-title"><Target size={14} /> Capital optimizer</span>
    <button className="btn btn-sm" onClick={() => openProof(optimize.receipt_id)}><Eye size={11} /> Proof</button></div>
    <div className="grid-12">{Object.entries(optimize.proposals || {}).map(([profile, p]: any) => <div className="panel col-4" key={profile} style={{ background: 'var(--bg)' }}>
      <div className="panel-header"><span className="panel-title" style={{ textTransform: 'capitalize' }}>{profile}</span><span className="badge badge-blue">{p.evidence?.label || 'UNKNOWN'}</span></div>
      <table className="table"><tbody>{Object.entries(p.proposed_pct || {}).map(([k, v]: any) => <tr key={k}><td className="muted">{k.replace(/_/g, ' ')}</td><td className="text-right mono">{v}%</td><td className="text-right mono">{fmtUsd(p.proposed_usd?.[k])}</td></tr>)}</tbody></table>
      <div className="muted mt-8" style={{ fontSize: 10 }}>{p.basis}</div>
    </div>)}</div><p className="muted mt-8" style={{ fontSize: 10 }}>{optimize.disclaimer}</p>
  </div>
}

function ProofDrawer({ proof, close }: { proof: any; close: () => void }) {
  const lane = proof.focus_lane ? proof.lanes_evidence?.[proof.focus_lane] : null
  const factIds = new Set<string>(lane?.facts_used || [])
  const facts = lane ? (proof.facts || []).filter((f: any) => factIds.has(f.evidence_id)) : (proof.facts || [])
  return <div className="panel mb-8" style={{ borderColor: 'var(--accent)' }}>
    <div className="panel-header"><span className="panel-title"><Database size={14} /> {lane ? `${lane.label} proof` : 'Capital proof graph'}</span><button className="btn btn-sm" onClick={close}><X size={11} /> Close</button></div>
    {lane && <div className="grid-12 mb-8"><MiniMetric label="Quality" value={`${lane.quality_label} ${lane.quality_score}%`} /><MiniMetric label="Observed" value={`${lane.observed_pct}%`} /><MiniMetric label="Assumed" value={`${lane.assumption_pct}%`} /><MiniMetric label="Conflicts" value={lane.conflict_count} /><MiniMetric label="Stale" value={lane.facts_stale?.length || 0} /><MiniMetric label="Missing" value={lane.facts_missing?.length || 0} /></div>}
    <div className="table-wrap"><table className="table"><thead><tr><th>Metric</th><th>Value</th><th>State</th><th>Provider</th><th>Fresh</th><th>Fact ID</th></tr></thead><tbody>
      {facts.map((f: any) => <tr key={f.evidence_id}><td>{f.domain}.{f.metric}</td><td className="mono">{fmtNum(f.value, 6)} {f.unit}</td><td>{stateBadge(f.state)}</td><td>{f.provider}</td><td>{f.fresh ? 'yes' : 'NO'}</td><td className="mono" style={{ fontSize: 9 }}>{f.evidence_id}</td></tr>)}
    </tbody></table></div>
    <div className="flex-between mt-8"><span className="muted" style={{ fontSize: 10 }}>{proof.proof_contract?.path}</span><span className="badge badge-blue">{proof.graph?.nodes?.length || 0} nodes · {proof.graph?.edges?.length || 0} edges</span></div>
  </div>
}
