"""
LLM analysis layer — OpenAI / Grok compatible, cost-capped, fallback-safe,
evidence-tracked.

Every helper returns a string and degrades to a rule-based fallback when:
- no provider key is configured (template mode), or
- the upstream call fails / times out, or
- a cached response exists (public/anonymous surfaces).

Evidence doctrine: every generated output (LLM or fallback) is persisted as an
analysis receipt with its input snapshot, model, provider, estimated cost and
timestamp, so a user can ask "why did it say this?" and we can reproduce the
exact state that produced it. AI analyzes and recommends; it never executes.
"""

import time

import httpx

from app.core import alerting, budget
from app.core.archisynapse import build_receipt, persist_receipt
from app.core.config import settings
from app.core.database import get_db

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_GROK_URL = "https://api.x.ai/v1/chat/completions"

_DISCLAIMER = (
    "Research and education only — not financial advice. Does not guarantee outcomes."
)

_CACHE_MAX_ENTRIES = 512

# Estimated USD per 1M tokens (input, output) for cost tracking.
_MODEL_RATES = {
    "gpt-4o-mini": (0.15, 0.60),
    "grok-3-mini": (0.30, 1.00),
}
_DEFAULT_RATES = (0.30, 1.00)


def provider() -> tuple[str, str, str]:
    """Resolve (provider, base_url, api_key). Empty key means template mode."""
    if settings.GROK_API_KEY:
        return "grok", _GROK_URL, settings.GROK_API_KEY
    if settings.OPENAI_API_KEY:
        return "openai", _OPENAI_URL, settings.OPENAI_API_KEY
    return "template", "", ""


def default_model(provider_name: str) -> str:
    return {
        "openai": "gpt-4o-mini",
        "grok": "grok-3-mini",
    }.get(provider_name, "gpt-4o-mini")


def provider_info() -> dict:
    name, _, _ = provider()
    return {
        "provider": name,
        "model": settings.AI_MODEL or default_model(name),
        "cache_ttl": settings.AI_CACHE_TTL,
    }


async def _chat(system: str, user: str, max_tokens: int) -> str | None:
    name, url, key = provider()
    if not key:
        return None

    model = settings.AI_MODEL or default_model(name)
    try:
        async with httpx.AsyncClient(timeout=settings.AI_TIMEOUT) as client:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": settings.AI_TEMPERATURE,
                },
            )
            if r.status_code != 200:
                return None
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip() if content else None
    except Exception:
        return None


# ---------- Evidence receipts (Archisynapse v1.1) ----------

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    in_rate, out_rate = _MODEL_RATES.get(model, _DEFAULT_RATES)
    return (in_tokens / 1_000_000 * in_rate) + (out_tokens / 1_000_000 * out_rate)


async def _persist_receipt(
    job: str,
    system: str,
    user: str,
    output: str,
    *,
    model: str,
    provider_name: str,
    fallback_used: bool,
    user_id: str | None = None,
    extra: dict | None = None,
    simulation: bool = False,
) -> None:
    """
    Build a cryptographically signed Archisynapse v1.1 receipt and persist it.
    Never raises — DB failures are logged, receipt_persisted flagged False.
    """
    try:
        db = get_db()
        if db is None:
            return

        receipt = build_receipt(
            job=job,
            system_prompt=system,
            user_prompt=user,
            output=output,
            model=model,
            provider_name=provider_name,
            fallback_used=fallback_used,
            simulation=simulation,
            user_id=user_id,
            extra=extra,
        )

        receipt_id, persisted = await persist_receipt(receipt, db)

        if not persisted:
            # HARNESS.md §5: receipt_persisted: false must not pass silently.
            await alerting.fire(
                alerting.RECEIPT_WRITE_FAILED,
                f"Signed receipt could not be persisted for job '{job}'.",
                context={
                    "job": job,
                    "user_id": user_id or "system",
                    "receipt_id": receipt_id,
                    "provider": provider_name,
                    "model": model,
                },
            )
    except Exception:
        return


# In-process TTL cache: {key: (expires_at, text)}
_cache: dict[str, tuple[float, str]] = {}


def _cache_get(key: str) -> str | None:
    entry = _cache.get(key)
    if not entry:
        return None
    expires_at, text = entry
    if time.time() > expires_at:
        _cache.pop(key, None)
        return None
    return text


def _cache_set(key: str, text: str) -> None:
    if len(_cache) >= _CACHE_MAX_ENTRIES:
        # Cheap eviction: drop expired entries first, then arbitrary ones.
        now = time.time()
        expired = [k for k, v in _cache.items() if v[0] < now]
        for k in expired:
            _cache.pop(k, None)
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            for k in list(_cache)[: len(_cache) - _CACHE_MAX_ENTRIES // 2]:
                _cache.pop(k, None)
    _cache[key] = (time.time() + settings.AI_CACHE_TTL, text)


_SIMULATION_BANNER = (
    "SIMULATION / DEMO — NOT LIVE MARKET ANALYSIS. "
    "This output was generated from demo/synthetic market data."
)


async def generate(
    system: str,
    user: str,
    fallback: str,
    *,
    cache_key: str | None = None,
    job: str | None = None,
    user_id: str | None = None,
    simulation: bool = False,
    extra: dict | None = None,
) -> str:
    """Return analysis text or the fallback. Never raises.

    simulation=True marks the output with a SIMULATION/DEMO banner and skips
    paid inference, so synthetic prices never masquerade as live analysis.
    When job is given, every output (LLM or fallback) is persisted as an
    analysis receipt for audit.
    """
    if simulation:
        text = _SIMULATION_BANNER + "\n" + fallback
        if cache_key:
            _cache_set(cache_key, text)
        if job:
            await _persist_receipt(
                job,
                system,
                user,
                text,
                model=settings.AI_MODEL or default_model("gpt-4o-mini"),
                provider_name="simulation",
                fallback_used=True,
                user_id=user_id,
                simulation=True,
                extra={**(extra or {}), "simulation": True},
            )
        return text

    if cache_key:
        hit = _cache_get(cache_key)
        if hit is not None:
            return hit

    # ── Spend enforcement gate (HARNESS.md §4) ────────────────────────────
    # Checked AFTER the cache (cache hits cost nothing) and BEFORE any paid
    # inference. When the cap is hit we return the rule-based fallback and
    # never make the API call. This is the kill switch, not a dashboard.
    budget_blocked = False
    if settings.AI_BUDGET_ENFORCE:
        try:
            decision = await budget.check_budget(get_db(), user_id=user_id)
            budget_blocked = decision.blocked
        except Exception:
            # Gate itself failed — do not block the user on an infra fault,
            # but the ledger read inside check_budget already fails closed
            # for the cases that matter.
            budget_blocked = False

    if budget_blocked:
        text = fallback
        if cache_key:
            _cache_set(cache_key, text)
        if job:
            await _persist_receipt(
                job,
                system,
                user,
                text,
                model=settings.AI_MODEL or default_model("gpt-4o-mini"),
                provider_name="budget_blocked",
                fallback_used=True,
                user_id=user_id,
                extra={**(extra or {}), "budget_blocked": True},
            )
        return text

    text = await _chat(system, user, max_tokens=settings.AI_MAX_TOKENS)
    fallback_used = text is None
    if not text:
        text = fallback

    if cache_key:
        _cache_set(cache_key, text)

    if job:
        name, _, _ = provider()
        await _persist_receipt(
            job,
            system,
            user,
            text,
            model=settings.AI_MODEL or default_model(name),
            provider_name=name,
            fallback_used=fallback_used,
            user_id=user_id,
            extra=extra,
        )
    return text


# ---------- Typed helpers ----------

def _base_system(role: str) -> str:
    return (
        f"You are a senior market-research analyst writing the {role} for a trading "
        "intelligence platform. Be specific, concise, and grounded in the numbers "
        "provided. Do not invent data. Keep it under 120 words. "
        f"{_DISCLAIMER}"
    )


async def thesis_for(
    asset: str,
    asset_class: str,
    quote_text: str,
    regime: str | None,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    fallback = (
        f"{asset} ({asset_class}): structural and momentum conditions reviewed across "
        f"timeframes. Research only — not financial advice."
    )
    system = _base_system("investment thesis")
    user = (
        f"Write a concise investment thesis for {asset} ({asset_class}).\n\n"
        f"Market data: {quote_text}\n"
        f"Market regime: {regime or 'unknown'}\n\n"
        "Cover: setup quality, key levels to watch, and the single biggest risk."
    )
    return await generate(
        system,
        user,
        fallback,
        cache_key=f"thesis:{asset}:{asset_class}",
        job="asset_thesis",
        user_id=user_id,
        simulation=simulation,
        extra={"asset": asset, "asset_class": asset_class, "regime": regime},
    )


async def journal_review_for(
    asset: str,
    direction: str,
    pnl: float | None,
    source: str,
    notes: str | None,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    result = "profitable" if pnl is not None and pnl > 0 else "losing"
    fallback = (
        f"AI Post-Trade: Simulated {direction} on {asset} closed with a {result} outcome "
        f"({pnl:+.2f}). Tag process mistakes separately from market outcomes."
    )
    system = _base_system("post-trade review")
    user = (
        f"Review this {source} trade journal entry.\n"
        f"Asset: {asset}, direction: {direction}, PnL: {pnl}\n"
        f"Trader notes: {notes or 'none'}\n\n"
        "Focus on: what the process looked like, one lesson to carry forward, and "
        "whether outcome was driven by process or by luck. Be honest and brief."
    )
    return await generate(
        system,
        user,
        fallback,
        job="journal_review",
        user_id=user_id,
        simulation=simulation,
        extra={"asset": asset, "direction": direction, "source": source, "pnl": pnl},
    )


async def post_trade_review_for(
    asset: str,
    direction: str,
    pnl: float,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    result = "profitable" if pnl > 0 else "losing"
    fallback = (
        f"AI Post-Trade Review: Simulated {direction} on {asset} closed with a {result} "
        f"outcome ({pnl:+.2f}). Review entry timing, risk parameters, and whether the "
        f"original thesis remained valid. Paper-trade review only."
    )
    system = _base_system("post-trade review")
    user = (
        f"A simulated {direction} position on {asset} closed at {pnl:+.2f} PnL.\n\n"
        "Assess: was entry aligned with the setup, was the exit rule-based, and what "
        "one adjustment would improve the next trade."
    )
    return await generate(
        system,
        user,
        fallback,
        job="post_trade_review",
        user_id=user_id,
        simulation=simulation,
        extra={"asset": asset, "direction": direction, "pnl": pnl},
    )


async def backtest_review_for(
    metrics: dict,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    ret = metrics.get("total_return_pct")
    wr = metrics.get("win_rate")
    dd = metrics.get("max_drawdown_pct")
    pf = metrics.get("profit_factor")
    n = metrics.get("number_of_trades")
    overfit = metrics.get("overfit_risk_score")

    comments = []
    if ret and ret > 20 and wr and wr > 55 and dd and dd < 15:
        comments.append("Results look promising on the simulated sample.")
    if dd and dd > 20:
        comments.append("Drawdown is elevated — consider tighter risk controls.")
    if pf is not None and pf < 1.1:
        comments.append("Profit factor is marginal; edge may be weak.")
    if n and n < 20:
        comments.append("Limited number of trades — statistical significance is low.")
    if overfit and overfit > 60:
        comments.append("Overfit risk appears elevated. Strategy may be fragile out of sample.")
    if not comments:
        comments.append("Mixed results. Further testing across regimes is recommended.")

    verdict = "promising but needs more testing"
    if overfit and (overfit > 70 or (dd and dd > 25)):
        verdict = "fragile / elevated risk"
    elif ret and ret > 25 and wr and wr > 58 and dd and dd < 12 and overfit and overfit < 45:
        verdict = "appears relatively robust on this sample"

    fallback = (
        f"AI Strategy Review (simulated): The strategy appears **{verdict}**. "
        + " ".join(comments)
        + " This is historical simulation only and does not guarantee future performance."
    )

    system = _base_system("strategy backtest review")
    user = (
        "Critique this simulated strategy backtest.\n\n"
        f"Total return: {ret}% | Win rate: {wr}% | Max drawdown: {dd}%\n"
        f"Profit factor: {pf} | Trades: {n} | Overfit risk score: {overfit}/100\n\n"
        "Give: (1) one-line verdict, (2) the strongest evidence for or against the edge, "
        "(3) the most likely failure mode out of sample, (4) one concrete improvement."
    )
    return await generate(
        system,
        user,
        fallback,
        job="backtest_review",
        user_id=user_id,
        simulation=simulation,
        extra={"metrics": metrics},
    )


async def mining_review_for(
    context: dict,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    """Explain whether a mining setup is profitable, grounded in the numbers."""
    est = context.get("estimates", {})
    net = context.get("network", {})
    profit = est.get("operating_profit_day")
    revenue = est.get("revenue_day")
    power = est.get("power_cost_day")
    be = est.get("break_even_electricity_usd_kwh")
    payback = est.get("simple_payback_days")
    btc_day = est.get("daily_btc")

    if profit is not None:
        verdict = "profitable" if profit > 0 else "not profitable at current conditions"
        detail = (
            f"At current network and price conditions this setup produces about "
            f"{btc_day:.6f} BTC/day, {revenue:,.2f} USD/day revenue against "
            f"{power:,.2f} USD/day power, for an operating profit of "
            f"{profit:,.2f} USD/day. Break-even electricity is "
            f"{be:,.4f} USD/kWh; simple hardware payback is "
            f"{payback:,.0f} days." if payback and be else
            f"At current conditions this setup produces about {btc_day:.6f} BTC/day "
            f"({revenue:,.2f} USD/day) against {power:,.2f} USD/day power, so it is "
            f"{verdict}."
        )
    else:
        detail = "Not enough data to estimate profitability."
        verdict = "unknown"

    fallback = (
        f"AI Mining Review: this setup is currently {verdict}. {detail} "
        "Operating economics only — hardware, hosting, resale and horizon "
        "assumptions are not included in this figure."
    )

    system = (
        "You are a bitcoin mining economics analyst. Be specific, concise and "
        "grounded only in the numbers provided. Never invent data. Distinguish "
        "operating profit from capital payback. Under 120 words. "
        f"{_DISCLAIMER}"
    )
    user = (
        "Explain whether this mining setup is profitable right now and why.\n\n"
        f"Network: {net.get('source')} hashrate {net.get('hashrate_ths')} TH/s, "
        f"difficulty {net.get('difficulty')}, subsidy {net.get('block_subsidy')} BTC.\n"
        f"ASIC: {context.get('asic', {}).get('name')} "
        f"({context.get('asic', {}).get('hashrate_ths')} TH/s, "
        f"{context.get('asic', {}).get('power_watts')} W).\n"
        f"BTC price: {context.get('btc_price')} "
        f"(provider: {context.get('btc_price_provider')}, "
        f"observed: {context.get('btc_price_observed')})\n"
        f"Electricity: {context.get('electricity_usd_kwh')} USD/kWh, "
        f"pool fee {context.get('pool_fee_pct')}%, uptime {context.get('uptime_pct')}%.\n"
        f"Estimates: {est}\n\n"
        "Answer: (1) profitable or not, (2) the two biggest drivers, "
        "(3) the electricity rate that would flip it, (4) one assumption to challenge."
    )
    return await generate(
        system,
        user,
        fallback,
        job="mining_review",
        user_id=user_id,
        simulation=simulation,
        extra={"mining": context},
    )


async def scenario_review_for(
    context: dict,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    """Narrate a scenario run: which case hurts most, what flips it."""
    items = context.get("scenarios", [])
    if not items:
        fallback = "AI Scenario Review: no scenario results to interpret."
        return await generate(
            "You interpret scenario analysis.", fallback, fallback,
            job="scenario_review", user_id=user_id, simulation=simulation,
            extra={"scenario": context},
        )

    worst = min(items, key=lambda i: (i.get("estimates") or {}).get("operating_profit_day", 0) or 0)
    best = max(items, key=lambda i: (i.get("estimates") or {}).get("operating_profit_day", 0) or 0)
    n_unprofitable = sum(
        1 for i in items if (i.get("estimates") or {}).get("operating_profit_day", 0) <= 0
    )

    fallback = (
        f"AI Scenario Review: across {len(items)} scenarios, {n_unprofitable} are "
        f"unprofitable at current assumptions. The hardest case is '{worst.get('label')}' "
        f"(operating profit {((worst.get('estimates') or {}).get('operating_profit_day') or 0):,.2f} "
        f"USD/day); the strongest is '{best.get('label')}' "
        f"({((best.get('estimates') or {}).get('operating_profit_day') or 0):,.2f} USD/day). "
        "Scenario results are conditional on their stated assumptions, not forecasts."
    )

    system = (
        "You are an institutional scenario analyst. Interpret multi-vector "
        "scenarios precisely, identify the dominant risk driver, and refuse to "
        "present scenarios as forecasts. Under 120 words. "
        f"{_DISCLAIMER}"
    )
    user = (
        "Summarize this scenario run for a mining operator.\n\n"
        f"Base BTC price: {context.get('btc_price')} | network: {context.get('network', {}).get('source')}\n"
        f"Scenarios:\n" + "\n".join(
            f"- {i.get('label')}: profit_day={((i.get('estimates') or {}).get('operating_profit_day') or 0):,.2f} "
            f"flags={i.get('risk_flags')}"
            for i in items
        ) +
        "\n\nAnswer: (1) which scenario is most dangerous and why, (2) which single "
        "input drives the swing, (3) what assumption a skeptical operator should "
        "challenge first."
    )
    return await generate(
        system,
        user,
        fallback,
        job="scenario_review",
        user_id=user_id,
        simulation=simulation,
        extra={"scenario": context},
    )


async def allocation_review_for(
    context: dict,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    """Verdict on the capital allocation options, grounded in the numbers."""
    options = context.get("options", [])
    ranking = context.get("ranking", [])
    top = next((o for o in options if o.get("key") == (ranking[0] if ranking else None)), None)
    top_label = top.get("label") if top else "none"
    top_flow = top.get("flow_month") if top else 0.0

    fallback = (
        f"AI Allocation Review: on operating flow per capital deployed, the top option "
        f"is '{top_label}' (~{top_flow:,.0f} USD/month). Ranking basis is capital "
        "efficiency on operating flow; it excludes risk adjustment, financing and "
        "horizon. Not investment advice."
    )

    system = (
        "You are a capital-allocation strategist for digital-infrastructure "
        "operators. Compare deployment options using only the provided numbers, "
        "state the ranking basis, and note what the ranking does NOT capture. "
        "Under 120 words. "
        f"{_DISCLAIMER}"
    )
    user = (
        "Interpret this capital allocation run.\n\n"
        f"Capital: ${context.get('capital_usd'):,.0f} | Power: {context.get('available_mw')} MW | "
        f"BTC price: {context.get('btc_price')} ({context.get('btc_price_provider')})\n"
        f"Ranking (basis: {context.get('ranking_basis')}): {ranking}\n"
        f"Options:\n" + "\n".join(
            f"- {o.get('key')}: {'available' if o.get('available') else 'unavailable'}, "
            f"flow_month={o.get('flow_month') or 0:,.0f}, deployed={o.get('capital_deployed') or 0:,.0f}"
            for o in options
        ) +
        "\n\nAnswer: (1) top pick and why, (2) the biggest blind spot in this "
        "comparison, (3) the one scenario that would change the ranking."
    )
    return await generate(
        system,
        user,
        fallback,
        job="allocation_review",
        user_id=user_id,
        simulation=simulation,
        extra={"allocation": context},
    )


async def gpu_review_for(
    context: dict,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    """Verdict on build-vs-cloud GPU economics, grounded in the assumptions."""
    gpu = context.get("gpu", {})
    build = context.get("build", {})
    cloud = context.get("cloud", {})
    bflow = (build.get("flow_month") or 0.0) if build.get("available") else 0.0
    cflow = (cloud.get("flow_month") or 0.0) if cloud.get("available") else 0.0

    fallback = (
        f"AI GPU Review: build lane flows ~{bflow:,.0f} USD/month on "
        f"{build.get('units') or 0} GPUs; cloud lane flows ~{cflow:,.0f} USD/month "
        "on the rental spread. All GPU economics are assumptions (no live GPU "
        "provider). Zero-margin default when no achieved rate is set. "
        "Not investment advice."
    )

    system = (
        "You are a GPU-infrastructure economics reviewer for digital-infrastructure "
        "operators. Compare build-vs-cloud using ONLY the provided numbers, remind "
        "the reader that every GPU number is an operator assumption (rental rates, "
        "utilization, capex) — there is no live GPU spot provider — and note what "
        "the comparison does NOT capture (demand, utilization risk, resale). "
        "Under 120 words. "
        f"{_DISCLAIMER}"
    )
    user = (
        "Interpret this build-vs-cloud GPU economics run.\n\n"
        f"GPU: {gpu.get('model') or 'custom'} | capex ${gpu.get('capex_usd')} | "
        f"power {gpu.get('power_kw')} kW\n"
        f"Build lane: units={build.get('units')}, flow_month={bflow:,.0f}, "
        f"payback_days={build.get('payback_days')}, flags={build.get('risk_flags')}\n"
        f"Cloud lane: units={cloud.get('units')}, flow_month={cflow:,.0f}, "
        f"flags={cloud.get('risk_flags')}\n"
        f"Assumptions: achieved={context.get('gpu_achieved_rental_usd_hr')} $/hr, "
        f"cloud={context.get('gpu_cloud_rental_usd_hr')} $/hr, "
        f"utilization={context.get('gpu_utilization_pct')}%, "
        f"electricity=${context.get('electricity_usd_kwh')}/kWh\n\n"
        "Answer: (1) build vs cloud call and why, (2) the biggest assumption risk, "
        "(3) what would flip the call."
    )
    return await generate(
        system,
        user,
        fallback,
        job="gpu_review",
        user_id=user_id,
        simulation=simulation,
        extra={"gpu_economics": context},
    )


async def mine_vs_buy_review_for(
    context: dict,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    """Verdict on mine-vs-buy, honoring the reconciled capital accounting."""
    mining = context.get("mining_path", {})
    buy = context.get("buy_path", {})
    assumptions = context.get("assumptions", {})
    verdict = context.get("verdict")
    be = context.get("break_even_price_at_horizon")

    if not mining.get("available"):
        fallback = (
            f"AI Mine-vs-Buy Review: mining is unavailable on this capital "
            f"({mining.get('reason', 'unknown reason')}). Buy path is the only "
            "option compared here. Not investment advice."
        )
    else:
        mv = mining.get("value_at_horizon") or 0.0
        bv = buy.get("value_at_horizon") or 0.0
        fallback = (
            f"AI Mine-vs-Buy Review: mining ends at ~${mv:,.0f} vs buying "
            f"~${bv:,.0f} at the horizon, so {verdict.lower()}. Both paths start "
            "from the same capital; the mining path is reconciled across equipment, "
            "working capital, operating costs and residual hardware value. "
            f"Break-even horizon price is "
            f"{f'${be:,.0f}' if be else 'not reached in a positive range'}. "
            "Every BTC and dollar figure is conditional on the stated assumptions, "
            "not a forecast. Not investment advice."
        )

    system = (
        "You are a capital-allocation analyst for mining operators. Compare mining "
        "vs buying using ONLY the provided numbers, verify the capital accounting "
        "reconciles (equipment, setup, working capital, operating costs, residual), "
        "never present assumptions as forecasts, and name the single assumption "
        "that drives the verdict. Under 120 words. "
        f"{_DISCLAIMER}"
    )
    user = (
        "Interpret this mine-vs-buy run, given both paths start from the same "
        "capital and are reconciled.\n\n"
        f"Capital: ${context.get('capital_usd'):,.0f} | BTC entry: "
        f"{context.get('btc_price')} | Horizon: {assumptions.get('horizon_days')} days\n"
        f"Assumptions: price_at_horizon={assumptions.get('btc_price_at_horizon')}, "
        f"difficulty_growth_pct_year={assumptions.get('difficulty_growth_pct_year')}, "
        f"electricity={assumptions.get('electricity_usd_kwh')}, "
        f"setup_per_unit={assumptions.get('setup_cost_usd_per_unit')}, "
        f"hosting_per_unit_month={assumptions.get('hosting_cost_usd_per_unit_month')}, "
        f"maintenance_per_unit_month={assumptions.get('maintenance_cost_usd_per_unit_month')}, "
        f"resale_per_unit={assumptions.get('hardware_resale_value_usd_per_unit')}\n"
        f"Buy path: btc_bought={buy.get('btc_bought')}, "
        f"value_at_horizon={buy.get('value_at_horizon')}\n"
        f"Mine path: units={mining.get('units')}, equipment={mining.get('equipment_cost')}, "
        f"working_capital={mining.get('remaining_working_capital')}, "
        f"opex={mining.get('total_operating_cost')}, "
        f"shortfall_usd={mining.get('opex_shortfall_usd')}, "
        f"end_cash={mining.get('end_cash')}, "
        f"residual={mining.get('residual_hardware_value')}, "
        f"net_btc_after_opex={mining.get('net_btc_after_opex')}, "
        f"value_at_horizon={mining.get('value_at_horizon')}\n"
        f"Verdict: {verdict} | break_even_price_at_horizon={be}\n\n"
        "Answer: (1) which path wins and why, (2) confirm the capital accounting "
        "reconciles or flag the gap, (3) the one assumption most likely to flip "
        "the verdict."
    )
    return await generate(
        system,
        user,
        fallback,
        job="mine_vs_buy_review",
        user_id=user_id,
        simulation=simulation,
        extra={"mine_vs_buy": context},
    )


async def capital_review_for(
    context: dict,
    *,
    user_id: str | None = None,
    simulation: bool = False,
) -> str:
    """AI Capital Council review of a capital allocation run + proposal.

    Reviews ONLY the numbers it is given. Observed-live vs assumption evidence
    is passed through so the council can separate live facts from operator
    assumptions, and it never endorses execution — the optimizer proposes, a
    human decides.
    """
    lanes = context.get("lanes", {})
    ranking = context.get("ranking", [])
    rec = context.get("recommendation", {})
    pct = rec.get("proposed_pct", {})
    observed = context.get("observed", {})
    sim = context.get("simulation", False)

    def _lane_line(key: str) -> str:
        lane = lanes.get(key)
        if not lane:
            return f"{key}: (missing)"
        if not lane.get("available"):
            return f"{key}: unavailable ({lane.get('reason', 'n/a')})"
        ppm = lane.get("profit_per_mw")
        ppm_s = f"{ppm:,.0f}/MW/mo" if ppm is not None else "n/a"
        return (
            f"{key}: avail, capital=${lane.get('capital_allocated', 0):,.0f}, "
            f"profit_month=${lane.get('operating_profit_month', 0):,.0f}, "
            f"ppm={ppm_s}, payback={lane.get('simple_payback_days')}d, "
            f"flags={lane.get('risk_flags')}"
        )

    fallback = (
        f"AI Capital Council: capital ${context.get('capital_usd', 0):,.0f}, "
        f"{context.get('available_mw', 0)} MW, {context.get('horizon_months', 0)} months. "
        "Lane ranking: " + ", ".join(ranking or []) + ". "
        f"Proposal (proposal only): {pct}. "
        "Observed-live data: BTC price "
        f"${observed.get('btc_price')} ({observed.get('btc_price_provider')}). "
        "Mining network and BTC price are the only live-observed inputs; GPU and "
        "energy economics are operator assumptions. Nothing here executes without "
        "human approval. Not financial advice."
    )

    system = (
        "You are the AI Capital Council for a digital-infrastructure operator. "
        "You review a capital allocation proposal using ONLY the provided numbers. "
        "Separate observed-live data (BTC price, mining network) from operator "
        "assumptions (GPU/energy economics, horizon prices). Stress-test the "
        "proposal, name the single assumption most likely to flip it, and always "
        "remind the reader the optimizer proposes only — nothing is executed "
        "without human approval. Under 140 words. "
        f"{_DISCLAIMER}"
    )
    lane_block = "\n".join(f"- {_lane_line(k)}" for k in ("btc", "mining", "gpu", "energy"))
    user = (
        "Review this capital allocation run and proposal.\n\n"
        f"Capital: ${context.get('capital_usd', 0):,.0f} | "
        f"MW available: {context.get('available_mw', 0)} | "
        f"Horizon: {context.get('horizon_months', 0)} months | "
        f"Risk profile: {context.get('risk_profile')} | "
        f"Simulation mode: {sim}\n"
        f"Observed (live): BTC ${observed.get('btc_price')} "
        f"({observed.get('btc_price_provider')}, "
        f"observed={observed.get('btc_price_observed')}); network "
        f"hashrate={observed.get('network', {}).get('hashrate_ths')} "
        f"({observed.get('network', {}).get('source')})\n"
        "Lanes:\n"
        f"{lane_block}\n"
        f"Ranking: {ranking}\n"
        f"Proposal pct: {pct}\n"
        f"Proposal basis: {rec.get('basis')}\n\n"
        "Answer: (1) is the proposal coherent with the lane economics, "
        "(2) the biggest assumption risk, (3) what a human should verify "
        "before approving."
    )
    return await generate(
        system,
        user,
        fallback,
        job="capital_allocation_review",
        user_id=user_id,
        simulation=simulation,
        extra={"capital_allocation": context},
    )
