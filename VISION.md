# VISION — Capital + Compute Intelligence Infrastructure

We are not building "the best AI trading app." We are building the financial
operating system for digital infrastructure: **Markets + Bitcoin mining +
energy + AI/GPU compute + treasury + risk + evidence.**

Model: Bloomberg Terminal (data + terminal + enterprise) × Goldman Marquee
(SecDB-style scenarios, firm-wide risk, APIs) × Tesla Megapack (vertically
integrate the software that controls physical assets).

## Three product surfaces

```text
MARKETS
Prices • Risk • Portfolio • Research • Scenarios

INFRASTRUCTURE
Mining • ASIC Fleets • Energy • AI/GPU Compute • Data Centers

CAPITAL
Treasury • Cash Flow • Capex • Financing • Mine-vs-Buy
Build-vs-Cloud • Allocation
```

## The stack every surface runs on

```text
LIVE DATA
    ↓
NORMALIZED STATE
    ↓
RISK / ECONOMICS ENGINES
    ↓
AI INTELLIGENCE
    ↓
EVIDENCE RECEIPTS
    ↓
API + TERMINAL + ENTERPRISE
```

Evidence is the product, not a compliance artifact. Every price, network
metric, calculation, AI conclusion and portfolio state is normalized,
timestamped, sourced and receipted. Paid tiers monetize the intelligence,
not the charts.

## Flagship decision product

"Where should the next $X of capital and Y MW of power go?"

```text
Buy BTC
vs. Buy mining equipment
vs. Expand existing fleet
vs. Buy GPUs
vs. Rent GPU capacity
vs. Sell/curtail power
vs. Hold cash
```

using real market prices, real network conditions, real energy assumptions,
real hardware characteristics, the customer's actual fleet/portfolio, and a
preserved evidence trail.

## Moats to build

1. SecDB-style scenario engine (N-dimensional what-if across price,
   difficulty, power, uptime, rates).
2. AI/GPU compute economics (build-vs-cloud, utilization, cooling,
   depreciation, revenue/compute-hour).
3. Derived data series: ASIC profitability curves, power-to-hash spreads,
   compute-power spreads, regional break-even electricity curves, fleet
   efficiency, realized-vs-theoretical output. Persist history now; it
   compounds into proprietary data.
4. Anonymized, permissioned operator benchmarks (Bloomberg data flywheel).

## Non-negotiables (locked with partner)

- **No synthetic live data.** `MARKET_DATA_MODE=demo` labels everything
  simulation; `live` returns only real providers and reports
  `503 no profitability claim made` rather than a made-up number.
- **Evidence everywhere.** No demo fallback in live mode; receipts separate
  observed data from assumptions; every AI output is persisted.
- **No "ROI."** Only operating profit, simple payback, and explicit capital
  basis. A single ROI number would smuggle in unstated assumptions.
- **Mining is the bridge, not the destination.** It connects finance +
  crypto + energy + physical infrastructure + compute. The end state is the
  megawatt-allocation engine across mining / GPU / storage / idle.
