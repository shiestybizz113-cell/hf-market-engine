# hf-market-engine

**AI Trading Intelligence OS** for Crypto, Stocks, ETFs, Forex, Macro & DeFi

> Research • Simulation • AI-Assisted Analysis • Risk Control  
> **Not financial advice. Does not guarantee profits.**

## Phase 1 Scope

- Multi-asset market research (Crypto via CoinGecko + Stocks/ETFs/Macro via abstraction layer)
- AI Signal Engine & Strategy Council
- Strategy Builder + Backtesting UI
- Paper Trading Engine
- Portfolio / P&L tracker
- Risk Engine (0–100 score)
- Algorithmic Execution Simulator (TWAP, VWAP, POV, IS, Iceberg, Adaptive)
- Trade Journal (auto-entry from paper closes & execution sims)
- Pricing tiers + System Health
- JWT Auth

**No real-money execution in Phase 1.**

## Pricing

| Plan | Price |
|------|-------|
| Free | $0/mo |
| Pro Trader | $59/mo |
| Advanced Trader | $199/mo |
| Team / Community | $699/mo |
| White Label | $5,000 setup + $1,499/mo |

## Tech Stack

- Frontend: React + TypeScript + Vite
- Backend: FastAPI (Python)
- Database: MongoDB
- Market data: CoinGecko + provider abstraction (ready for Polygon/Massive, Alpaca, Twelve Data)

## Quick Start

```bash
# Full stack
docker compose up --build

# Local backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Local frontend
cd frontend && npm install && npm run dev
```

## Architecture

See `docs/ARCHITECTURE.md`

## Disclaimer

This platform provides market research, simulation, and AI-assisted analysis. It is not financial advice and does not guarantee profits. Trading involves substantial risk of loss.
