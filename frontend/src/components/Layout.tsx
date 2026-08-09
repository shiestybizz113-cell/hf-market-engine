import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, CandlestickChart, Eye, Zap, Crosshair,
  FlaskConical, LineChart, FileText, Briefcase, Shield,
  Brain, BookOpen, BarChart3, CreditCard, Activity, Settings, Target,
  LogOut
} from 'lucide-react'

const nav = [
  { section: 'Markets', items: [
    { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/crypto', label: 'Crypto', icon: CandlestickChart },
    { to: '/stocks', label: 'Stocks', icon: CandlestickChart },
    { to: '/etfs', label: 'ETFs', icon: CandlestickChart },
    { to: '/macro', label: 'Macro', icon: Activity },
    { to: '/watchlist', label: 'Watchlist', icon: Eye },
  ]},
  { section: 'Intelligence', items: [
    { to: '/alpha', label: 'Alpha Scanner', icon: Crosshair },
    { to: '/correlations', label: 'Correlation Radar', icon: Zap },
    { to: '/signals', label: 'Signals', icon: Zap },
    { to: '/ai-council', label: 'AI Council', icon: Brain },
    { to: '/execution', label: 'Execution Research', icon: Target },
  ]},
  { section: 'Trading Lab', items: [
    { to: '/strategies', label: 'Strategy Lab', icon: FlaskConical },
    { to: '/backtesting', label: 'Backtesting', icon: LineChart },
    { to: '/paper', label: 'Paper Trading', icon: FileText },
    { to: '/portfolio', label: 'Portfolio', icon: Briefcase },
    { to: '/risk', label: 'Risk Engine', icon: Shield },
    { to: '/journal', label: 'Journal', icon: BookOpen },
  ]},
  { section: 'System', items: [
    { to: '/reports', label: 'Reports', icon: BarChart3 },
    { to: '/pricing', label: 'Pricing', icon: CreditCard },
    { to: '/health', label: 'System Health', icon: Activity },
    { to: '/settings', label: 'Settings', icon: Settings },
  ]},
]

export default function Layout() {
  const navigate = useNavigate()
  const logout = () => {
    localStorage.removeItem('token')
    navigate('/login')
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          hf-<span>market</span>-engine
        </div>
        <nav style={{ flex: 1, overflowY: 'auto' }}>
          {nav.map((group) => (
            <div key={group.section}>
              <div className="nav-section">{group.section}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                >
                  <item.icon size={14} />
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <button className="nav-item" onClick={logout} style={{ border: 'none', background: 'none', width: '100%', cursor: 'pointer' }}>
          <LogOut size={14} /> Logout
        </button>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="flex gap-12" style={{ alignItems: 'center' }}>
            <input
              placeholder="Search assets…"
              style={{ width: 220, padding: '5px 10px', fontSize: 12 }}
            />
            <span className="badge badge-amber">Regime: Loading…</span>
          </div>
          <div className="flex gap-8" style={{ alignItems: 'center' }}>
            <span className="badge badge-green">System OK</span>
            <button className="btn btn-primary btn-sm" onClick={() => navigate('/pricing')}>
              Upgrade
            </button>
          </div>
        </header>

        <div className="content">
          <Outlet />
        </div>

        <div className="disclaimer">
          This platform provides market research, simulation, and AI-assisted analysis.
          It is not financial advice and does not guarantee profits.
          Trading crypto, stocks, ETFs, forex and other assets involves substantial risk.
        </div>
      </div>
    </div>
  )
}
