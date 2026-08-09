import { useState } from 'react'
import { Brain, TrendingUp, Shield, Coins, Target } from 'lucide-react'

const ROLES = [
  {
    id: 'macro',
    title: 'Macro Analyst',
    icon: TrendingUp,
    color: 'badge-blue',
    summary: 'Overall market regime appears mixed. Risk-on signals in crypto are partially offset by dollar firmness and selective equity softness. Liquidity conditions remain adequate but not expansive.',
    points: [
      'BTC dominance stable — no extreme rotation yet',
      'DXY elevated — headwind for risk assets',
      'Equity-crypto correlation still positive but loosening short-term',
      'VIX contained — no acute fear regime',
    ],
    caution: 'A sharp move in rates or dollar could quickly shift the regime to risk-off.',
  },
  {
    id: 'quant',
    title: 'Quant Analyst',
    icon: Target,
    color: 'badge-neutral',
    summary: 'Momentum factors remain constructive on higher timeframes while short-term mean-reversion setups are appearing in overextended names. Volume confirmation is mixed.',
    points: [
      'Trend quality higher on 4h/1d than on 15m/1h',
      'Volatility compression visible on several large-cap pairs',
      'Backtest sample sizes remain limited for newer strategies — treat edge estimates cautiously',
      'Cross-sectional dispersion elevated → opportunity for relative value',
    ],
    caution: 'Overfit risk rises when rules are tuned to recent high-volatility windows.',
  },
  {
    id: 'risk',
    title: 'Risk Officer',
    icon: Shield,
    color: 'badge-amber',
    summary: 'Aggregate simulated exposure should stay within defined limits. Concentration in high-beta crypto-equity names elevates drawdown risk under a sudden risk-off move.',
    points: [
      'Recommend max single-name paper position ≤ 5% of simulated capital',
      'Correlation clusters (BTC–COIN–MSTR) can amplify losses',
      'Daily loss limits should be hard-enforced even in paper mode',
      'Kill-switch criteria: regime shift + portfolio DD > threshold',
    ],
    caution: 'Current regime does not justify elevated leverage or oversized positions.',
  },
  {
    id: 'defi',
    title: 'DeFi Strategist',
    icon: Coins,
    color: 'badge-green',
    summary: 'On-chain activity and major L1/L2 fee trends are supportive of continued interest, but liquidity depth varies widely. Yield opportunities exist but carry smart-contract and depeg risk.',
    points: [
      'Major L1s showing resilient fee generation',
      'Stablecoin flows remain a useful real-time sentiment proxy',
      'Avoid concentrating paper exposure in thin secondary tokens',
      'Protocol risk and oracle risk still material',
    ],
    caution: 'DeFi yields are not risk-free; treat them as compensation for multiple risk layers.',
  },
  {
    id: 'execution',
    title: 'Execution Coach',
    icon: Brain,
    color: 'badge-blue',
    summary: 'For paper trading: define entry, invalidation, size, and time stop before opening any simulated position. Review every closed trade for process adherence, not just P&L.',
    points: [
      'Write the thesis and invalidation in the trade notes field',
      'Size from risk (stop distance) not from conviction alone',
      'Prefer limit-style mental entries over chasing candles',
      'Post-trade: tag process mistakes separately from market mistakes',
    ],
    caution: 'Paper trading is only useful if you treat it with the same discipline as real capital.',
  },
]

export default function AICouncil() {
  const [active, setActive] = useState(ROLES[0].id)
  const role = ROLES.find(r => r.id === active)!

  return (
    <div>
      <div className="mb-8">
        <h2 style={{ fontSize: 18 }}>AI Strategy Council</h2>
        <p className="muted" style={{ fontSize: 12 }}>
          Multi-persona research panel. Explains opportunity, risk, invalidation and what could go wrong — never blind “buy/sell”.
        </p>
      </div>

      <div className="flex gap-8 mb-8" style={{ flexWrap: 'wrap' }}>
        {ROLES.map(r => (
          <button
            key={r.id}
            className={`btn btn-sm ${active === r.id ? 'btn-primary' : ''}`}
            onClick={() => setActive(r.id)}
          >
            <r.icon size={13} /> {r.title}
          </button>
        ))}
      </div>

      <div className="panel" style={{ borderColor: 'var(--amber)' }}>
        <div className="panel-header">
          <span className="panel-title flex gap-8" style={{ alignItems: 'center' }}>
            <role.icon size={14} /> {role.title}
          </span>
          <span className={`badge ${role.color}`}>AI Research</span>
        </div>

        <p style={{ fontSize: 13, lineHeight: 1.55, marginBottom: 14 }}>{role.summary}</p>

        <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          Key Observations
        </div>
        <ul style={{ paddingLeft: 18, marginBottom: 14, fontSize: 12 }}>
          {role.points.map((p, i) => <li key={i} style={{ marginBottom: 4 }}>{p}</li>)}
        </ul>

        <div className="panel" style={{ background: 'var(--bg)' }}>
          <div className="amber" style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>What Could Go Wrong</div>
          <p style={{ fontSize: 12 }}>{role.caution}</p>
        </div>
      </div>

      <div className="panel mt-8">
        <div className="panel-header"><span className="panel-title">Council Principles</span></div>
        <div className="grid-12" style={{ fontSize: 12 }}>
          <div className="col-6">• No blind buy/sell recommendations</div>
          <div className="col-6">• Always surface invalidation conditions</div>
          <div className="col-6">• Confidence and risk expressed explicitly</div>
          <div className="col-6">• Cross-asset context required for major ideas</div>
          <div className="col-6">• Paper-trade planning only in Phase 1</div>
          <div className="col-6">• Research ≠ advice; simulation ≠ performance</div>
        </div>
      </div>

      <p className="muted mt-8" style={{ fontSize: 11 }}>
        AI Council output is research and decision-support only. Not financial advice. Does not guarantee profits.
      </p>
    </div>
  )
}
