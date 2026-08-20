/**
 * DataModeBanner — governance harness component.
 *
 * Surfaces MARKET_DATA_MODE on every authenticated view.
 * In demo mode: non-dismissable amber strip, always visible.
 * In live mode: small persistent green indicator, always visible.
 *
 * Fail-visible: defaults to showing DEMO MODE immediately on mount.
 * If the health fetch fails, the banner stays amber — never hides.
 * This matches the VISION.md non-negotiable: no synthetic data can
 * silently masquerade as live.
 */

import { useEffect, useState } from 'react'
import { AlertTriangle, Radio, RefreshCw } from 'lucide-react'
import { getHealth } from '../services/api'

type DataMode = 'demo' | 'live'

export default function DataModeBanner() {
  // Default to demo — show immediately, update when fetch confirms.
  // If fetch fails, stays demo (fail-visible, never silent).
  const [mode, setMode] = useState<DataMode>('demo')
  const [lastChecked, setLastChecked] = useState<Date | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const fetchMode = async () => {
    try {
      const res = await getHealth()
      const resolved: DataMode =
        res.data?.market_data_mode === 'live' ? 'live' : 'demo'
      setMode(resolved)
      setLastChecked(new Date())
    } catch {
      // Network error or backend down — stay on current mode (demo by default)
      // Do not hide the banner. Fail visible.
    }
  }

  useEffect(() => {
    fetchMode()
    const interval = setInterval(fetchMode, 2 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  const handleRefresh = async () => {
    setRefreshing(true)
    await fetchMode()
    setRefreshing(false)
  }

  // ── DEMO MODE ─────────────────────────────────────────────────────────────
  if (mode === 'demo') {
    return (
      <div style={{
        background: 'rgba(245, 158, 11, 0.08)',
        borderBottom: '1px solid rgba(245, 158, 11, 0.25)',
        padding: '7px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        fontSize: 12,
        color: 'var(--amber)',
        userSelect: 'none',
        flexShrink: 0,
      }}>
        <AlertTriangle size={13} strokeWidth={2.5} style={{ flexShrink: 0 }} />
        <span style={{ fontWeight: 600, letterSpacing: '0.3px' }}>DEMO MODE</span>
        <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>
          All prices are simulated. No real capital is at risk.
          Set{' '}
          <code style={{
            background: 'rgba(245,158,11,0.12)',
            padding: '0 5px',
            borderRadius: 3,
            fontSize: 11,
            fontFamily: 'ui-monospace, monospace',
          }}>MARKET_DATA_MODE=live</code>
          {' '}in your{' '}
          <code style={{
            background: 'rgba(245,158,11,0.12)',
            padding: '0 5px',
            borderRadius: 3,
            fontSize: 11,
            fontFamily: 'ui-monospace, monospace',
          }}>.env</code>
          {' '}to connect real data providers.
        </span>
        <button
          onClick={handleRefresh}
          title="Re-check data mode"
          style={{
            marginLeft: 'auto',
            background: 'none',
            border: 'none',
            color: 'var(--amber)',
            cursor: 'pointer',
            padding: '2px 4px',
            opacity: 0.7,
            display: 'flex',
            alignItems: 'center',
            flexShrink: 0,
          }}
        >
          <RefreshCw
            size={11}
            strokeWidth={2}
            style={{
              transition: 'transform 0.6s',
              transform: refreshing ? 'rotate(360deg)' : 'none',
            }}
          />
        </button>
      </div>
    )
  }

  // ── LIVE MODE ─────────────────────────────────────────────────────────────
  return (
    <div style={{
      background: 'rgba(34, 197, 94, 0.06)',
      borderBottom: '1px solid rgba(34, 197, 94, 0.15)',
      padding: '5px 20px',
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      fontSize: 11,
      color: 'var(--positive)',
      flexShrink: 0,
    }}>
      <Radio size={11} strokeWidth={2.5} />
      <span style={{ fontWeight: 600, letterSpacing: '0.5px' }}>LIVE DATA</span>
      <span style={{ color: 'var(--text-faint)', fontWeight: 400 }}>
        Real market prices. All AI outputs are receipted and timestamped.
      </span>
      {lastChecked && (
        <span style={{ marginLeft: 'auto', color: 'var(--text-faint)', fontSize: 10 }}>
          verified {lastChecked.toLocaleTimeString()}
        </span>
      )}
    </div>
  )
}
