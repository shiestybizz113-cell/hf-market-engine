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
import LiveMarket from './pages/LiveMarket'
import AlphaScanner from './pages/AlphaScanner'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import Capital from './pages/Capital'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('token')
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />

      <Route element={<PrivateRoute><Layout /></PrivateRoute>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/crypto" element={<LiveMarket market="crypto" />} />
        <Route path="/stocks" element={<LiveMarket market="stock" />} />
        <Route path="/etfs" element={<LiveMarket market="etf" />} />
        <Route path="/macro" element={<LiveMarket market="macro" />} />
        <Route path="/watchlist" element={<Watchlist />} />
        <Route path="/alpha" element={<AlphaScanner />} />
        <Route path="/capital" element={<Capital />} />
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
        <Route path="/reports" element={<Reports />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/health" element={<SystemHealth />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/asset/:symbol" element={<AssetDetail />} />
      </Route>
    </Routes>
  )
}
