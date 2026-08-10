import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Pricing from './pages/Pricing'
import Watchlist from './pages/Watchlist'
import Strategies from './pages/Strategies'
import PaperTrading from './pages/PaperTrading'
import Risk from './pages/Risk'
import Backtesting from './pages/Backtesting'
import AICouncil from './pages/AICouncil'
import AssetDetail from './pages/AssetDetail'
import ExecutionResearch from './pages/ExecutionResearch'
import Portfolio from './pages/Portfolio'
import Journal from './pages/Journal'
import SystemHealth from './pages/SystemHealth'
import Correlations from './pages/Correlations'
import Signals from './pages/Signals'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

function Placeholder({ title }: { title: string }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">{title}</span>
      </div>
      <p className="muted">Module ready for next iteration.</p>
      <p className="muted mt-8" style={{ fontSize: 11 }}>
        Research & simulation only. Not financial advice.
      </p>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />

      <Route element={<PrivateRoute><Layout /></PrivateRoute>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/crypto" element={<Placeholder title="Crypto Markets" />} />
        <Route path="/stocks" element={<Placeholder title="Stocks" />} />
        <Route path="/etfs" element={<Placeholder title="ETFs" />} />
        <Route path="/macro" element={<Placeholder title="Macro / Forex" />} />
        <Route path="/watchlist" element={<Watchlist />} />
        <Route path="/alpha" element={<Placeholder title="Alpha Scanner" />} />
        <Route path="/correlations" element={<Correlations />} />
        <Route path="/signals" element={<Signals />} />
        <Route path="/ai-council" element={<AICouncil />} />
        <Route path="/execution" element={<ExecutionResearch />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/backtesting" element={<Backtesting />} />
        <Route path="/paper" element={<PaperTrading />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/journal" element={<Journal />} />
        <Route path="/reports" element={<Placeholder title="Reports" />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/health" element={<SystemHealth />} />
        <Route path="/settings" element={<Placeholder title="Settings" />} />
        <Route path="/asset/:symbol" element={<AssetDetail />} />
      </Route>
    </Routes>
  )
}
