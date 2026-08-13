"""Infrastructure market-data fabric for Capital Command Center V2.

This module normalizes hardware, GPU-compute, and energy observations into the
same immutable EvidenceFact store used by market/mining data.

Production feeds are configured as canonical JSON endpoints:
  HARDWARE_OFFERS_URL -> {"offers": [...]}
  GPU_OFFERS_URL      -> {"offers": [...]}
  ENERGY_PRICES_URL   -> {"prices": [...]}

If a feed is not configured or is unavailable, reference catalog facts remain
USER_ASSUMPTION. Nothing is promoted to OBSERVED_LIVE without an observed
provider payload.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.core import evidence as E
from app.core.config import settings
from app.core.database import get_db
from app.core.evidence_broker import capture_observation, resolve_metric
from app.core.gpu import GPU_CATALOG
from app.core.mining import ASIC_CATALOG


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return _now()


def _items(payload: Any, key: str) -> List[Dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        raw = payload.get(key, payload.get("data", []))
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    return []


def _public_fact(doc: Dict) -> Dict:
    out = dict(doc)
    out.pop("_id", None)
    out["fresh"] = not E.is_stale(out)
    out["age_seconds"] = round(E.age_seconds(out), 1)
    return out


async def _store_snapshot(
    *, domain: str, provider: str, source_reference: str, payload: Any,
    observed_at: Optional[datetime] = None, _db=None,
) -> str:
    db = _db or get_db()
    snapshot_id = str(uuid.uuid4())
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    doc = {
        "_id": snapshot_id,
        "snapshot_id": snapshot_id,
        "domain": domain,
        "provider": provider,
        "source_reference": source_reference,
        "observed_at": observed_at or _now(),
        "ingested_at": _now(),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "payload": payload,
    }
    await db.provider_snapshots.insert_one(doc)
    return f"snapshot:{snapshot_id}"


async def _fetch_json(url: str) -> Any:
    timeout = float(getattr(settings, "INFRA_PROVIDER_TIMEOUT", 10.0))
    token = getattr(settings, "INFRA_PROVIDER_BEARER_TOKEN", "")
    headers = {"Accept": "application/json", "User-Agent": "hf-market-engine/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


async def seed_reference_catalogs(_db=None) -> Dict[str, int]:
    """Seed/refresh reference hardware + GPU facts as assumptions, never live."""
    db = _db or get_db()
    hardware = 0
    compute = 0

    for model, item in ASIC_CATALOG.items():
        common = {
            "domain": "hardware",
            "subject_id": model,
            "state": E.USER_ASSUMPTION,
            "provider": "reference_catalog",
            "source_type": "reference",
            "source_reference": "internal:ASIC_CATALOG",
            "methodology": "Versioned internal reference catalog; indicative, not a live quote",
            "extra": {"model": model, "name": item.get("model"), "class": item.get("class")},
            "_db": db,
        }
        await capture_observation(metric="asic_hashrate", value=float(item["hashrate_ths"]), unit="ths", **common)
        await capture_observation(metric="asic_power", value=float(item["power_watts"]), unit="watts", **common)
        await capture_observation(metric="asic_price", value=float(item["price_usd"]), unit="usd", **common)
        hardware += 3

    for model, item in GPU_CATALOG.items():
        common = {
            "domain": "gpu",
            "subject_id": model,
            "state": E.USER_ASSUMPTION,
            "provider": "reference_catalog",
            "source_type": "reference",
            "source_reference": "internal:GPU_CATALOG",
            "methodology": "Versioned internal reference catalog; indicative, not a live quote",
            "extra": {"gpu_model": model, "name": item.get("model")},
            "_db": db,
        }
        await capture_observation(metric="gpu_capex", value=float(item["capex_usd"]), unit="usd", **common)
        await capture_observation(metric="gpu_power", value=float(item["power_kw"]), unit="kw", **common)
        await capture_observation(
            domain="gpu",
            metric="compute_offer",
            subject_id=f"{model}|reference|global|on_demand",
            value=float(item["cloud_rental_usd_hr"]),
            unit="usd_gpu_hr",
            state=E.USER_ASSUMPTION,
            provider="reference_catalog",
            source_type="reference",
            source_reference="internal:GPU_CATALOG",
            methodology="Indicative cloud rental reference, not a live provider quote",
            extra={
                "gpu_model": model,
                "name": item.get("model"),
                "region": "global",
                "billing_model": "on_demand",
                "availability": "reference_only",
            },
            _db=db,
        )
        compute += 3

    return {"hardware_facts_seeded": hardware, "compute_facts_seeded": compute}


async def refresh_hardware_offers(_db=None) -> Dict:
    db = _db or get_db()
    await seed_reference_catalogs(db)
    url = getattr(settings, "HARDWARE_OFFERS_URL", "")
    if not url:
        return {"configured": False, "observed": 0, "status": "reference_only"}

    provider_default = getattr(settings, "HARDWARE_PROVIDER_ID", "hardware_feed")
    try:
        payload = await _fetch_json(url)
        observed = _now()
        snapshot_ref = await _store_snapshot(
            domain="hardware", provider=provider_default, source_reference=url,
            payload=payload, observed_at=observed, _db=db,
        )
        count = 0
        for item in _items(payload, "offers"):
            model = str(item.get("model") or item.get("asic_model") or "").strip()
            price = item.get("price_usd", item.get("price"))
            if not model or price is None or float(price) <= 0:
                continue
            provider = str(item.get("provider") or provider_default)
            region = item.get("region")
            condition = str(item.get("condition") or "new")
            source_type = str(item.get("source_type") or "live_api")
            observed_at = _parse_dt(item.get("observed_at"))
            extra = {
                "model": model,
                "name": item.get("name") or model,
                "condition": condition,
                "quantity": item.get("quantity"),
                "shipping_usd": item.get("shipping_usd"),
                "region": region,
            }
            await capture_observation(
                domain="hardware", metric="asic_price",
                subject_id=f"{model}|{provider}|{region or 'global'}|{condition}",
                value=float(price), unit="usd", state=E.OBSERVED_LIVE,
                provider=provider, source_type=source_type,
                source_reference=str(item.get("source_reference") or url),
                observed_at=observed_at, region=region,
                methodology="Normalized observed hardware market offer",
                raw_snapshot_ref=snapshot_ref, extra=extra, _db=db,
            )
            if item.get("hashrate_ths") is not None:
                await capture_observation(
                    domain="hardware", metric="asic_hashrate", subject_id=model,
                    value=float(item["hashrate_ths"]), unit="ths",
                    state=E.OBSERVED_LIVE, provider=provider, source_type=source_type,
                    source_reference=str(item.get("source_reference") or url),
                    observed_at=observed_at, region=region,
                    methodology="Hardware offer/spec observation",
                    raw_snapshot_ref=snapshot_ref, extra={"model": model}, _db=db,
                )
            if item.get("power_watts") is not None:
                await capture_observation(
                    domain="hardware", metric="asic_power", subject_id=model,
                    value=float(item["power_watts"]), unit="watts",
                    state=E.OBSERVED_LIVE, provider=provider, source_type=source_type,
                    source_reference=str(item.get("source_reference") or url),
                    observed_at=observed_at, region=region,
                    methodology="Hardware offer/spec observation",
                    raw_snapshot_ref=snapshot_ref, extra={"model": model}, _db=db,
                )
            count += 1
        return {"configured": True, "observed": count, "status": "ok"}
    except Exception as exc:
        return {"configured": True, "observed": 0, "status": "degraded", "error": str(exc)}


async def refresh_compute_offers(_db=None) -> Dict:
    db = _db or get_db()
    await seed_reference_catalogs(db)
    url = getattr(settings, "GPU_OFFERS_URL", "")
    if not url:
        return {"configured": False, "observed": 0, "status": "reference_only"}

    provider_default = getattr(settings, "GPU_PROVIDER_ID", "gpu_feed")
    try:
        payload = await _fetch_json(url)
        observed = _now()
        snapshot_ref = await _store_snapshot(
            domain="gpu", provider=provider_default, source_reference=url,
            payload=payload, observed_at=observed, _db=db,
        )
        count = 0
        for item in _items(payload, "offers"):
            model = str(item.get("gpu_model") or item.get("model") or "").strip()
            rate = item.get("price_per_gpu_hour", item.get("price_usd_hr"))
            if not model or rate is None or float(rate) <= 0:
                continue
            provider = str(item.get("provider") or provider_default)
            region = str(item.get("region") or "global")
            billing = str(item.get("billing_model") or item.get("market") or "on_demand")
            observed_at = _parse_dt(item.get("observed_at"))
            extra = {
                "gpu_model": model,
                "gpu_count": item.get("gpu_count"),
                "region": region,
                "billing_model": billing,
                "availability": item.get("availability"),
                "minimum_commitment": item.get("minimum_commitment"),
                "vram_gb": item.get("vram_gb"),
                "power_kw": item.get("power_kw"),
            }
            await capture_observation(
                domain="gpu", metric="compute_offer",
                subject_id=f"{model}|{provider}|{region}|{billing}",
                value=float(rate), unit="usd_gpu_hr", state=E.OBSERVED_LIVE,
                provider=provider, source_type="live_api",
                source_reference=str(item.get("source_reference") or url),
                observed_at=observed_at, region=region,
                methodology="Normalized observed GPU compute offer",
                raw_snapshot_ref=snapshot_ref, extra=extra, _db=db,
            )
            if item.get("capex_usd") is not None:
                await capture_observation(
                    domain="gpu", metric="gpu_capex", subject_id=model,
                    value=float(item["capex_usd"]), unit="usd", state=E.OBSERVED_LIVE,
                    provider=provider, source_type="live_api",
                    source_reference=str(item.get("source_reference") or url),
                    observed_at=observed_at, region=region,
                    methodology="Observed GPU hardware offer",
                    raw_snapshot_ref=snapshot_ref, extra={"gpu_model": model}, _db=db,
                )
            if item.get("power_kw") is not None:
                await capture_observation(
                    domain="gpu", metric="gpu_power", subject_id=model,
                    value=float(item["power_kw"]), unit="kw", state=E.OBSERVED_LIVE,
                    provider=provider, source_type="live_api",
                    source_reference=str(item.get("source_reference") or url),
                    observed_at=observed_at, region=region,
                    methodology="Observed/provider GPU power specification",
                    raw_snapshot_ref=snapshot_ref, extra={"gpu_model": model}, _db=db,
                )
            count += 1
        return {"configured": True, "observed": count, "status": "ok"}
    except Exception as exc:
        return {"configured": True, "observed": 0, "status": "degraded", "error": str(exc)}


async def refresh_energy_prices(_db=None) -> Dict:
    db = _db or get_db()
    url = getattr(settings, "ENERGY_PRICES_URL", "")
    if not url:
        return {"configured": False, "observed": 0, "status": "unconfigured"}

    provider_default = getattr(settings, "ENERGY_PROVIDER_ID", "energy_feed")
    try:
        payload = await _fetch_json(url)
        observed = _now()
        snapshot_ref = await _store_snapshot(
            domain="energy", provider=provider_default, source_reference=url,
            payload=payload, observed_at=observed, _db=db,
        )
        count = 0
        for item in _items(payload, "prices"):
            region = str(item.get("region") or item.get("node") or "unknown")
            price_type = str(item.get("price_type") or "wholesale")
            raw_kwh = item.get("price_usd_kwh")
            raw_mwh = item.get("price_usd_mwh")
            if raw_kwh is None and raw_mwh is None:
                continue
            price_kwh = float(raw_kwh) if raw_kwh is not None else float(raw_mwh) / 1000.0
            provider = str(item.get("provider") or provider_default)
            observed_at = _parse_dt(item.get("observed_at"))
            source_type = price_type if price_type in {"wholesale", "tariff", "contract"} else "live_api"
            extra = {
                "region": region,
                "price_type": price_type,
                "demand_charge_usd_kw": item.get("demand_charge_usd_kw"),
                "time_window": item.get("time_window"),
                "delivered_operator_cost": bool(item.get("delivered_operator_cost", False)),
            }
            await capture_observation(
                domain="energy", metric="power_price",
                subject_id=f"{region}|{price_type}|{provider}",
                value=price_kwh, unit="usd_kwh", state=E.OBSERVED_LIVE,
                provider=provider, source_type=source_type,
                source_reference=str(item.get("source_reference") or url),
                observed_at=observed_at, region=region,
                methodology="Normalized observed energy price; wholesale is not automatically operator delivered cost",
                raw_snapshot_ref=snapshot_ref, extra=extra, _db=db,
            )
            count += 1
        return {"configured": True, "observed": count, "status": "ok"}
    except Exception as exc:
        return {"configured": True, "observed": 0, "status": "degraded", "error": str(exc)}


async def refresh_all(_db=None) -> Dict:
    db = _db or get_db()
    hardware = await refresh_hardware_offers(db)
    compute = await refresh_compute_offers(db)
    energy = await refresh_energy_prices(db)
    return {"hardware": hardware, "compute": compute, "energy": energy}


async def _query_product_facts(
    *, domain: str, metric: str, user_id: Optional[str], product_key: Optional[str] = None,
    product_value: Optional[str] = None, region: Optional[str] = None,
    billing_model: Optional[str] = None, limit: int = 200, _db=None,
) -> List[Dict]:
    db = _db or get_db()
    scope = [None] + ([user_id] if user_id else [])
    query: Dict[str, Any] = {"domain": domain, "metric": metric, "user_id": {"$in": scope}}
    if product_key and product_value:
        query[f"extra.{product_key}"] = product_value
    if region:
        query["region"] = region
    if billing_model:
        query["extra.billing_model"] = billing_model
    cursor = db.evidence_facts.find(query).sort("observed_at", -1).limit(limit)
    return [doc async for doc in cursor]


def _resolve_candidates(facts: List[Dict], *, explicit: bool = False) -> Dict:
    fresh = [f for f in facts if not E.is_stale(f)]
    candidates = fresh if fresh else facts
    summary = E.summarize_resolution(candidates, explicit_user_input=explicit)
    summary["stale_candidate_count"] = sum(1 for f in facts if E.is_stale(f))
    return summary


async def resolve_hardware_bundle(
    model: str, user_id: Optional[str], *, explicit_price: Optional[float] = None,
    explicit_hashrate: Optional[float] = None, explicit_power_watts: Optional[float] = None,
    _db=None,
) -> Dict:
    db = _db or get_db()
    await refresh_hardware_offers(db)

    if explicit_price is not None:
        await capture_observation(
            domain="hardware", metric="asic_price", subject_id=f"{model}|user_input",
            value=float(explicit_price), unit="usd", state=E.USER_ASSUMPTION,
            provider="user_input", source_type="user_input", user_id=user_id,
            methodology="Operator-supplied ASIC purchase/reference price",
            extra={"model": model}, _db=db,
        )
    if explicit_hashrate is not None:
        await capture_observation(
            domain="hardware", metric="asic_hashrate", subject_id=model,
            value=float(explicit_hashrate), unit="ths", state=E.USER_ASSUMPTION,
            provider="user_input", source_type="user_input", user_id=user_id,
            methodology="Operator-supplied ASIC hashrate", extra={"model": model}, _db=db,
        )
    if explicit_power_watts is not None:
        await capture_observation(
            domain="hardware", metric="asic_power", subject_id=model,
            value=float(explicit_power_watts), unit="watts", state=E.USER_ASSUMPTION,
            provider="user_input", source_type="user_input", user_id=user_id,
            methodology="Operator-supplied ASIC power", extra={"model": model}, _db=db,
        )

    prices = await _query_product_facts(
        domain="hardware", metric="asic_price", user_id=user_id,
        product_key="model", product_value=model, _db=db,
    )
    price = _resolve_candidates(prices, explicit=explicit_price is not None)
    hashrate = await resolve_metric(
        domain="hardware", metric="asic_hashrate", subject_id=model, user_id=user_id, _db=db,
    )
    power = await resolve_metric(
        domain="hardware", metric="asic_power", subject_id=model, user_id=user_id, _db=db,
    )
    return {"price": price, "hashrate": hashrate, "power": power}


async def resolve_compute_bundle(
    model: str, user_id: Optional[str], *, region: Optional[str] = None,
    billing_model: Optional[str] = None, explicit_capex: Optional[float] = None,
    explicit_power_kw: Optional[float] = None, explicit_cloud_rate: Optional[float] = None,
    _db=None,
) -> Dict:
    db = _db or get_db()
    await refresh_compute_offers(db)

    if explicit_capex is not None:
        await capture_observation(
            domain="gpu", metric="gpu_capex", subject_id=model,
            value=float(explicit_capex), unit="usd", state=E.USER_ASSUMPTION,
            provider="user_input", source_type="user_input", user_id=user_id,
            methodology="Operator-supplied GPU capex", extra={"gpu_model": model}, _db=db,
        )
    if explicit_power_kw is not None:
        await capture_observation(
            domain="gpu", metric="gpu_power", subject_id=model,
            value=float(explicit_power_kw), unit="kw", state=E.USER_ASSUMPTION,
            provider="user_input", source_type="user_input", user_id=user_id,
            methodology="Operator-supplied GPU power", extra={"gpu_model": model}, _db=db,
        )
    if explicit_cloud_rate is not None:
        await capture_observation(
            domain="gpu", metric="compute_offer",
            subject_id=f"{model}|user_input|{region or 'global'}|{billing_model or 'on_demand'}",
            value=float(explicit_cloud_rate), unit="usd_gpu_hr", state=E.USER_ASSUMPTION,
            provider="user_input", source_type="user_input", user_id=user_id, region=region,
            methodology="Operator-supplied cloud compute price",
            extra={"gpu_model": model, "region": region or "global", "billing_model": billing_model or "on_demand"},
            _db=db,
        )

    capex = await resolve_metric(domain="gpu", metric="gpu_capex", subject_id=model, user_id=user_id, _db=db)
    power = await resolve_metric(domain="gpu", metric="gpu_power", subject_id=model, user_id=user_id, _db=db)
    offers = await _query_product_facts(
        domain="gpu", metric="compute_offer", user_id=user_id,
        product_key="gpu_model", product_value=model, region=region,
        billing_model=billing_model, _db=db,
    )
    offer = _resolve_candidates(offers, explicit=explicit_cloud_rate is not None)
    return {"capex": capex, "power": power, "cloud_offer": offer}


async def resolve_energy_market(
    user_id: Optional[str], *, region: Optional[str] = None, _db=None,
) -> Dict:
    db = _db or get_db()
    await refresh_energy_prices(db)
    facts = await _query_product_facts(
        domain="energy", metric="power_price", user_id=user_id, region=region, _db=db,
    )
    return _resolve_candidates(facts)


async def list_hardware_offers(user_id: Optional[str], _db=None) -> Dict:
    db = _db or get_db()
    refresh = await refresh_hardware_offers(db)
    facts = await _query_product_facts(domain="hardware", metric="asic_price", user_id=user_id, _db=db)
    return {"refresh": refresh, "count": len(facts), "offers": [_public_fact(f) for f in facts]}


async def list_compute_offers(
    user_id: Optional[str], *, model: Optional[str] = None, region: Optional[str] = None,
    billing_model: Optional[str] = None, _db=None,
) -> Dict:
    db = _db or get_db()
    refresh = await refresh_compute_offers(db)
    facts = await _query_product_facts(
        domain="gpu", metric="compute_offer", user_id=user_id,
        product_key="gpu_model" if model else None, product_value=model,
        region=region, billing_model=billing_model, _db=db,
    )
    return {"refresh": refresh, "count": len(facts), "offers": [_public_fact(f) for f in facts]}


async def list_energy_prices(user_id: Optional[str], *, region: Optional[str] = None, _db=None) -> Dict:
    db = _db or get_db()
    refresh = await refresh_energy_prices(db)
    facts = await _query_product_facts(
        domain="energy", metric="power_price", user_id=user_id, region=region, _db=db,
    )
    return {
        "refresh": refresh,
        "count": len(facts),
        "prices": [_public_fact(f) for f in facts],
        "warning": "Wholesale market power price is context, not automatically the operator's delivered electricity cost.",
    }
