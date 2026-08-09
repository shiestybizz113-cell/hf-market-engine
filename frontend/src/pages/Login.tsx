import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { login } from '../services/api'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await login(email, password)
      localStorage.setItem('token', res.data.access_token)
      navigate('/dashboard')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>hf-market-engine</h1>
        <p className="sub">AI Trading Intelligence OS</p>
        <form onSubmit={submit}>
          <div className="form-row">
            <label>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} required />
          </div>
          <div className="form-row">
            <label>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} required />
          </div>
          {error && <div className="negative mb-8" style={{ fontSize: 12 }}>{error}</div>}
          <button className="btn btn-primary" style={{ width: '100%' }} disabled={loading}>
            {loading ? 'Signing in…' : 'Launch Terminal'}
          </button>
        </form>
        <p className="muted mt-12" style={{ fontSize: 12, textAlign: 'center' }}>
          No account? <Link to="/register" style={{ color: 'var(--accent)' }}>Create one</Link>
        </p>
        <p className="muted mt-8" style={{ fontSize: 10, textAlign: 'center' }}>
          Research & simulation only. Not financial advice.
        </p>
      </div>
    </div>
  )
}
