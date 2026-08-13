import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/register')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

export default api

// Auth
export const register = (email: string, password: string, full_name?: string) =>
  api.post('/auth/register', { email, password, full_name })

export const login = (email: string, password: string) => {
  const form = new URLSearchParams()
  form.append('username', email)
  form.append('password', password)
  return api.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}

export const getMe = () => api.get('/auth/me')

// Market
export const getOverview = () => api.get('/market/overview')
export const getMovers = (asset_class = 'crypto') => api.get(`/market/movers?asset_class=${asset_class}`)
export const getSignals = (limit = 10) => api.get(`/market/signals?limit=${limit}`)
export const getCorrelations = () => api.get('/market/correlations')
export const getAsset = (symbol: string, asset_class = 'crypto') =>
  api.get(`/market/asset/${symbol}?asset_class=${asset_class}`)
export const getPrices = (symbols: string, asset_class = 'crypto') =>
  api.get(`/market/prices?symbols=${symbols}&asset_class=${asset_class}`)

// Trading
export const getWatchlist = () => api.get('/watchlist')
export const addWatchlist = (symbol: string, asset_class: string) =>
  api.post('/watchlist', { symbol, asset_class })
export const removeWatchlist = (id: string) => api.delete(`/watchlist/${id}`)
export const getStrategies = () => api.get('/strategies')
export const createStrategy = (data: any) => api.post('/strategies', data)
export const deleteStrategy = (id: string) => api.delete(`/strategies/${id}`)
export const runBacktest = (data: any) => api.post('/backtests', data)
export const getPaperTrades = (status?: string) => api.get(`/paper-trades${status ? `?status=${status}` : ''}`)
export const openPaperTrade = (data: any) => api.post('/paper-trades', data)
export const closePaperTrade = (id: string) => api.post(`/paper-trades/${id}/close`)
export const getPortfolio = () => api.get('/portfolio')
export const addHolding = (data: any) => api.post('/portfolio', data)
export const riskReviewStrategy = (data: any) => api.post('/risk-review/strategy', data)
export const riskReviewPaper = (data: any) => api.post('/risk-review/paper-trade', data)

// System + Billing
export const getHealth = () => api.get('/system/health')
export const getPlans = () => api.get('/billing/plans')
export const getBillingMe = () => api.get('/billing/me')
export const getBillingStatus = () => api.get('/billing/status')
export const createCheckout = (plan_id: string) => api.post('/billing/checkout', { plan_id })
export const devUpgrade = (plan_id: string) => api.post('/billing/dev-upgrade', { plan_id })
export const devDowngrade = (plan_id: string) => api.post('/billing/dev-downgrade', { plan_id })

// Journal
export const getJournal = () => api.get('/journal')

// Execution (Phase 1 paper simulation)
export const getExecutionAlgos = () => api.get('/execution/algos')
export const recommendAlgo = (params: { asset: string; asset_class?: string; side?: string; quantity?: number; urgency?: string }) =>
  api.post('/execution/recommend', null, { params })
export const submitExecutionOrder = (data: any) => api.post('/execution/orders', data)
export const listExecutionOrders = (status?: string) => api.get(`/execution/orders${status ? `?status=${status}` : ''}`)
export const getExecutionOrder = (id: string) => api.get(`/execution/orders/${id}`)
export const getExecutionAnalytics = (id: string) => api.get(`/execution/orders/${id}/analytics`)
export const cancelExecutionOrder = (id: string) => api.post(`/execution/orders/${id}/cancel`)

// Capital Allocation Command Center
export const runCapitalAllocation = (data: any) => api.post('/capital/run', data)
export const runCapitalScenarios = (data: any) => api.post('/capital/scenarios', data)
export const runCapitalOptimize = (data: any) => api.post('/capital/optimize', data)

// Capital V2 infrastructure market data
export const getHardwareOffers = () => api.get('/hardware/offers')
export const getComputeOffers = (params?: { model?: string; region?: string; billing_model?: string }) =>
  api.get('/compute/offers', { params })
export const getEnergyPrices = (region?: string) => api.get('/energy/prices', { params: region ? { region } : undefined })

// Operator asset/fleet registry — no hard delete by design
export const getAssets = (activeOnly = false) => api.get('/assets', { params: { active_only: activeOnly } })
export const getAssetSummary = () => api.get('/assets/summary')
export const createAsset = (data: any) => api.post('/assets', data)
export const updateAsset = (assetId: string, data: any) => api.patch(`/assets/${assetId}`, data)
export const importAssets = (assets: any[]) => api.post('/assets/import', { assets })
export const retireAsset = (assetId: string) => api.post(`/assets/${assetId}/retire`)
export const reactivateAsset = (assetId: string) => api.post(`/assets/${assetId}/reactivate`)

// Evidence fabric / proof graph
export const getEvidenceFacts = (params?: any) => api.get('/evidence/facts', { params })
export const getEvidenceFact = (evidenceId: string) => api.get(`/evidence/facts/${evidenceId}`)
export const getEvidenceGraph = (receiptId: string) => api.get(`/evidence/graph/${receiptId}`)
