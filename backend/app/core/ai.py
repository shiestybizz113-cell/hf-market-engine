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
import uuid
import httpx
from typing import Dict, Optional, Tuple

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


def provider() -> Tuple[str, str, str]:
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


def provider_info() -> Dict:
    name, _, _ = provider()
    return {
        "provider": name,
        "model": settings.AI_MODEL or default_model(name),
        "cache_ttl": settings.AI_CACHE_TTL,
    }


async def _chat(system: str, user: str, max_tokens: int) -> Optional[str]:
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


# ---------- Evidence receipts ----------

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
    user_id: Optional[str] = None,
    extra: Optional[Dict] = None,
) -> None:
    """Persist an analysis receipt best-effort. Never raises."""
    try:
        db = get_db()
        if db is None:
            return
        in_tokens = _estimate_tokens(system) + _estimate_tokens(user)
        out_tokens = _estimate_tokens(output)
        receipt = {
            "_id": str(uuid.uuid4()),
            "job": job,
            "user_id": user_id,
            "system_prompt": system,
            "user_prompt": user,
            "output": output,
            "model": model,
            "provider": provider_name,
            "fallback_used": fallback_used,
            "tokens_estimate": {"input": in_tokens, "output": out_tokens},
            "estimated_cost_usd": round(_estimate_cost(model, in_tokens, out_tokens), 6),
            "generated_at": time.time(),
        }
        if extra:
            receipt["extra"] = extra
        await db["analysis_receipts"].insert_one(receipt)
    except Exception:
        return


# In-process TTL cache: {key: (expires_at, text)}
_cache: Dict[str, Tuple[float, str]] = {}


def _cache_get(key: str) -> Optional[str]:
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
    cache_key: Optional[str] = None,
    job: Optional[str] = None,
    user_id: Optional[str] = None,
    simulation: bool = False,
    extra: Optional[Dict] = None,
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
                extra={**(extra or {}), "simulation": True},
            )
        return text

    if cache_key:
        hit = _cache_get(cache_key)
        if hit is not None:
            return hit

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
    regime: Optional[str],
    *,
    user_id: Optional[str] = None,
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
    pnl: Optional[float],
    source: str,
    notes: Optional[str],
    *,
    user_id: Optional[str] = None,
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
    user_id: Optional[str] = None,
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
    metrics: Dict,
    *,
    user_id: Optional[str] = None,
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
    context: Dict,
    *,
    user_id: Optional[str] = None,
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
        f"BTC price: {context.get('btc_price')}\n"
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
    context: Dict,
    *,
    user_id: Optional[str] = None,
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
    context: Dict,
    *,
    user_id: Optional[str] = None,
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
