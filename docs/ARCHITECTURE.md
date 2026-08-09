# hf-market-engine — Architecture (Phase 1)

## Modular Layers

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React + TypeScript + Vite)                       │
│  Dark trading terminal UI · 12-col dense grid               │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST / JWT
┌──────────────────────────▼──────────────────────────────────┐
│  API Layer (FastAPI)                                        │
│  /auth  /market  /watchlist  /strategies  /backtests        │
│  /paper-trades  /portfolio  /risk-review  /pricing  /system │
└──────────────────────────┬──────────────────────────────────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     ▼                     ▼                     ▼
┌─────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ Market Data │   │  AI / Signal    │   │  Risk Engine    │
│ Provider    │   │  Engine         │   │                 │
│ Layer       │   │                 │   │                 │
│             │   │  Trade Ideas    │   │  Score 0–100    │
│ CoinGecko   │   │  Regime         │   │  Block extreme  │
│ Demo (stocks│   │  Correlation    │   │                 │
│  ETFs, FX)  │   │  Alpha Scanner  │   │                 │
│ Ready for:  │   │  Ready for LLM  │   │                 │
│ Polygon,    │   └─────────────────┘   └─────────────────┘
│ Alpaca,     │
│ Twelve Data │
└─────────────┘
     │
     ▼
┌─────────────┐   ┌─────────────────┐   ┌─────────────────┐
│ Backtesting │   │ Paper Trading   │   │ Portfolio /     │
│ Engine      │   │ Engine          │   │ Journal         │
│ (simulated) │   │ (no real $)     │   │                 │
└─────────────┘   └─────────────────┘   └─────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  MongoDB                                                    │
│  users · watchlist · strategies · paper_trades · portfolio  │
│  backtests · journal                                        │
└─────────────────────────────────────────────────────────────┘
```

## Billing Layer (ready)

- Plans defined in `/api/pricing/plans`
- Upgrade CTAs show “Billing coming soon”
- Structure supports Stripe or Archisynapse later
- Plan gates already enforced (backtesting, paper trading blocked on Free)

## White-Label Layer (ready)

- Config-driven branding hooks can be added
- Team seats + shared workspace fields present in plan model
- Custom domain / logo support planned for White Label tier

## Phase 2 readiness

- Provider interface allows swapping DemoProvider → Polygon/Alpaca
- Paper trading engine can later emit orders via CCXT
- Kill-switch and risk rules already centralised in RiskEngine

## Disclaimers

Every major surface (dashboard footer, signal cards, pricing, backtests, paper trades) carries:

> This platform provides market research, simulation, and AI-assisted analysis.  
> It is not financial advice and does not guarantee profits.  
> Trading involves substantial risk.

## Phase 2 — Algorithmic Execution Engine

### Interface
`ExecutionEngineProtocol` defines:
- `submit_parent_order` / `cancel_parent_order`
- `get_parent_order` / `list_parent_orders`
- `get_analytics`
- `recommend_algo`

### Implementations
- **Phase 1**: `PaperExecutionEngine` — simulated slices + slippage, never hits real venues.
- **Phase 2**: `LiveExecutionEngine` (future) — CCXT / exchange APIs / SOR, still behind Risk Engine + explicit live flag.

### Models
- `ParentOrder` / `ChildOrder`
- `ExecutionAlgoConfig` (TWAP, VWAP, POV, IS, Iceberg, Adaptive, SOR)
- `ExecutionAnalytics` (implementation shortfall, VWAP deviation, fees, venue breakdown)
- Educational `ExecutionAlgoInfo` catalog served at `GET /api/execution/algos`

### Safety invariants
- `paper_mode=True` enforced in Phase 1
- Risk Engine remains non-bypassable gate
- Kill-switch / daily-loss / max-participation hard stops required before live
- Full child-order audit trail

### Frontend
- `/execution` — research panel explaining each strategy, crypto notes, Phase 2 readiness
