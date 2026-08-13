"""
Bitcoin Mining Intelligence — read-only mining economics, evidence-first.

Architecture (mirrors the market-data honesty contract):

    BTC price (market layer) + network data + ASIC/power inputs
        -> mining economics engine
        -> mine-vs-buy / scenarios / fleet
        -> AI explanation
        -> evidence receipt

Three locked rules:
  1. No demo fallback in live mode. If live BTC price or live network data is
     unavailable, the result is unavailable — never a synthetic live number.
  2. Mine vs Buy separates observed data from assumptions in the receipt.
     Difficulty growth, future BTC price, uptime, resale value and pool fees
     are assumptions/scenarios, not facts.
  3. Nothing is ever called "ROI". Daily operating profit and simple payback
     (hardware cost / daily profit) are reported with an explicit capital
     basis; a full ROI would require hosting, downtime, resale and horizon
     assumptions that we refuse to present as a single number.

Read-only economics + fleet intelligence only. No browser mining, no hidden
mining, no custody of rewards.
"""

import httpx
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.config import settings

BLOCKCHAIN_INFO_URL = "https://api.blockchain.info"
PROVIDER_TIMEOUT = 8.0

# Current on-chain consensus constants (observed at the network level, not
# assumptions): block subsidy is 3.125 BTC until the next halving; the network
# targets a 600s block interval.
BLOCK_SUBSIDY = 3.125
BLOCK_TIME_SECONDS = 600

SECONDS_PER_DAY = 86400
HASHES_PER_TERAHASH = 1e12
# Expected blocks/day when the network is running at the difficulty target.
NOMINAL_BLOCKS_PER_DAY = SECONDS_PER_DAY / BLOCK_TIME_SECONDS


@dataclass
class NetworkData:
    """Snapshot of the Bitcoin network that drives every estimate."""
    provider: str
    source: str  # "live" | "demo"
    observed_at: datetime
    hashrate_ths: float
    difficulty: float
    block_subsidy: float = BLOCK_SUBSIDY
    block_time_seconds: float = BLOCK_TIME_SECONDS

    @property
    def blocks_per_day(self) -> float:
        if self.difficulty <= 0:
            return 0.0
        return (self.hashrate_ths * HASHES_PER_TERAHASH * SECONDS_PER_DAY) / (self.difficulty * 2 ** 32)


class NetworkProvider(ABC):
    @abstractmethod
    async def fetch(self) -> Optional[NetworkData]:
        """Return live network data or None when unavailable. Never raises."""


class BlockchainInfoProvider(NetworkProvider):
    provider_id = "blockchain.info"

    async def fetch(self) -> Optional[NetworkData]:
        try:
            async with httpx.AsyncClient(timeout=PROVIDER_TIMEOUT) as client:
                hr, diff = await client.get(f"{BLOCKCHAIN_INFO_URL}/q/hashrate"), \
                           await client.get(f"{BLOCKCHAIN_INFO_URL}/q/getdifficulty")
                if hr.status_code != 200 or diff.status_code != 200:
                    return None
                hashrate_ghs = float(hr.text.strip())
                difficulty = float(diff.text.strip())
                if hashrate_ghs <= 0 or difficulty <= 0:
                    return None
                return NetworkData(
                    provider=self.provider_id,
                    source="live",
                    observed_at=datetime.now(timezone.utc),
                    hashrate_ths=hashrate_ghs / 1000.0,
                    difficulty=difficulty,
                )
        except Exception:
            return None


class DemoNetworkProvider(NetworkProvider):
    provider_id = "demo"

    async def fetch(self) -> Optional[NetworkData]:
        return NetworkData(
            provider="demo",
            source="demo",
            observed_at=datetime.now(timezone.utc),
            hashrate_ths=800_000_000,  # ~800 EH/s
            difficulty=110_000_000_000_000.0,  # ~110T
        )


# ---------- ASIC catalog ----------
# Realistic reference hardware. Prices are indicative street prices and are
# treated as user-editable inputs, not live quotes.
ASIC_CATALOG: Dict[str, dict] = {
    "S21 Pro": {"model": "Antminer S21 Pro", "hashrate_ths": 234.0, "power_watts": 3510.0, "price_usd": 3500.0, "class": "professional"},
    "S21": {"model": "Antminer S21", "hashrate_ths": 200.0, "power_watts": 3500.0, "price_usd": 2800.0, "class": "professional"},
    "S19k Pro": {"model": "Antminer S19k Pro", "hashrate_ths": 136.0, "power_watts": 3310.0, "price_usd": 2200.0, "class": "professional"},
    "S19 Pro": {"model": "Antminer S19 Pro", "hashrate_ths": 110.0, "power_watts": 3250.0, "price_usd": 1800.0, "class": "professional"},
    "M60S": {"model": "Whatsminer M60S", "hashrate_ths": 186.0, "power_watts": 3441.0, "price_usd": 3000.0, "class": "professional"},
    "M66S": {"model": "Whatsminer M66S", "hashrate_ths": 298.0, "power_watts": 5400.0, "price_usd": 4800.0, "class": "professional"},
    "A1566": {"model": "Avalon A1566", "hashrate_ths": 185.0, "power_watts": 3420.0, "price_usd": 2600.0, "class": "professional"},
    "A1366": {"model": "Avalon A1366", "hashrate_ths": 130.0, "power_watts": 3250.0, "price_usd": 2000.0, "class": "professional"},
    "Bitaxe Max": {"model": "Bitaxe Max (hobby)", "hashrate_ths": 0.6, "power_watts": 18.0, "price_usd": 150.0, "class": "hobby"},
}


def asic_for(model: str) -> Optional[dict]:
    return ASIC_CATALOG.get(model) or next(
        (v for v in ASIC_CATALOG.values() if v["model"].lower() == model.lower()), None
    )


# ---------- Economics engine ----------

def estimate_daily_btc(hashrate_ths: float, network: NetworkData, uptime_pct: float, pool_fee_pct: float) -> float:
    """Expected net BTC mined per day for one miner, after pool fee."""
    if hashrate_ths <= 0 or network.difficulty <= 0:
        return 0.0
    hashes = hashrate_ths * HASHES_PER_TERAHASH
    gross = (hashes * SECONDS_PER_DAY * network.block_subsidy) / (network.difficulty * 2 ** 32)
    gross *= uptime_pct / 100.0
    return gross * (1.0 - pool_fee_pct / 100.0)


def compute_estimate(
    *,
    hashrate_ths: float,
    power_watts: float,
    electricity_usd_kwh: float,
    pool_fee_pct: float,
    uptime_pct: float,
    btc_price: float,
    hardware_cost_usd: float,
    network: NetworkData,
) -> Dict:
    uptime = max(0.0, min(100.0, uptime_pct))
    daily_btc = estimate_daily_btc(hashrate_ths, network, uptime, pool_fee_pct)
    revenue_day = daily_btc * btc_price
    kwh_day = (power_watts / 1000.0) * 24.0 * (uptime / 100.0)
    power_cost_day = kwh_day * electricity_usd_kwh
    profit_day = revenue_day - power_cost_day
    break_even_kwh = revenue_day / kwh_day if kwh_day > 0 else None
    revenue_per_ths = revenue_day / hashrate_ths if hashrate_ths > 0 else 0.0
    payback_days = hardware_cost_usd / profit_day if profit_day > 0 else None
    monthly_profit = profit_day * 30.0
    annualized_profit = profit_day * 365.0

    return {
        "daily_btc": daily_btc,
        "revenue_per_ths_day": revenue_per_ths,
        "revenue_day": revenue_day,
        "power_cost_day": power_cost_day,
        "power_kwh_day": kwh_day,
        "operating_profit_day": profit_day,
        "operating_profit_month": monthly_profit,
        "operating_profit_year": annualized_profit,
        "break_even_electricity_usd_kwh": break_even_kwh,
        "simple_payback_days": payback_days,
        "capital_basis_usd": hardware_cost_usd,
        "roi_label": (
            "Not computed: full ROI requires hosting, downtime, resale and "
            "horizon assumptions. Only operating profit and simple hardware "
            "payback are reported."
        ),
    }


def scenario_table(
    base: Dict,
    btc_price: float,
    price_shifts_pct: List[float],
    difficulty_shifts_pct: List[float],
    difficulty: float,
    hashrate_ths: float,
    uptime_pct: float,
    pool_fee_pct: float,
    electricity_usd_kwh: float,
    power_watts: float,
    hardware_cost_usd: float,
) -> List[Dict]:
    rows = []
    for dpct in difficulty_shifts_pct:
        d = difficulty * (1 + dpct / 100.0)
        for ppct in price_shifts_pct:
            p = btc_price * (1 + ppct / 100.0)
            net = NetworkData(
                provider=base["network"]["provider"],
                source=base["network"]["source"],
                observed_at=base["network"]["observed_at"],
                hashrate_ths=base["network"]["hashrate_ths"],
                difficulty=d,
                block_subsidy=base["network"]["block_subsidy"],
                block_time_seconds=base["network"]["block_time_seconds"],
            )
            e = compute_estimate(
                hashrate_ths=hashrate_ths,
                power_watts=power_watts,
                electricity_usd_kwh=electricity_usd_kwh,
                pool_fee_pct=pool_fee_pct,
                uptime_pct=uptime_pct,
                btc_price=p,
                hardware_cost_usd=hardware_cost_usd,
                network=net,
            )
            rows.append({
                "btc_price_shift_pct": ppct,
                "difficulty_shift_pct": dpct,
                "btc_price": round(p, 2),
                "difficulty": d,
                "daily_btc": e["daily_btc"],
                "revenue_day": e["revenue_day"],
                "power_cost_day": e["power_cost_day"],
                "operating_profit_day": e["operating_profit_day"],
                "simple_payback_days": e["simple_payback_days"],
            })
    return rows


def mine_vs_buy(
    *,
    capital_usd: float,
    asic: Dict,
    btc_price: float,
    electricity_usd_kwh: float,
    pool_fee_pct: float,
    uptime_pct: float,
    horizon_days: int,
    difficulty_growth_pct_year: float,
    btc_price_at_horizon: float,
    network: NetworkData,
) -> Dict:
    units = int(capital_usd // asic["price_usd"]) if asic["price_usd"] > 0 else 0
    hardware_cost = units * asic["price_usd"]
    leftover = max(0.0, capital_usd - hardware_cost)

    buy_path_btc = capital_usd / btc_price if btc_price > 0 else 0.0

    if units <= 0:
        mining_path = {
            "units": 0,
            "available": False,
            "reason": f"Insufficient capital for one {asic['model']} (needs ~${asic['price_usd']:,.0f}).",
        }
    else:
        # Difficulty compounds over the horizon; use the mid-horizon difficulty
        # as the average burden for a linear approximation, stated as assumption.
        growth_factor = (1 + difficulty_growth_pct_year / 100.0) ** (horizon_days / 365.0)
        avg_difficulty = network.difficulty * (1 + growth_factor) / 2.0
        avg_net = NetworkData(
            provider=network.provider,
            source=network.source,
            observed_at=network.observed_at,
            hashrate_ths=network.hashrate_ths,
            difficulty=avg_difficulty,
            block_subsidy=network.block_subsidy,
            block_time_seconds=network.block_time_seconds,
        )
        per_unit_day = estimate_daily_btc(asic["hashrate_ths"], avg_net, uptime_pct, pool_fee_pct)
        mined_btc = per_unit_day * units * horizon_days
        power_kwh_day = (asic["power_watts"] / 1000.0) * 24.0 * (uptime_pct / 100.0) * units
        total_power_kwh = power_kwh_day * horizon_days
        total_power_cost = total_power_kwh * electricity_usd_kwh
        # Power paid out of capital; express holdings in BTC terms using the
        # horizon price assumption so both paths are compared in the same unit.
        net_btc = mined_btc - (total_power_cost / btc_price_at_horizon) if btc_price_at_horizon > 0 else mined_btc
        mining_path = {
            "units": units,
            "available": True,
            "hardware_cost": hardware_cost,
            "leftover_cash": leftover,
            "total_power_kwh": total_power_kwh,
            "total_power_cost": total_power_cost,
            "total_operating_cost": hardware_cost + total_power_cost,
            "mined_btc": mined_btc,
            "net_btc_after_power": net_btc,
            "value_at_horizon": net_btc * btc_price_at_horizon,
        }

    buy_path = {
        "btc_bought": buy_path_btc,
        "value_at_horizon": buy_path_btc * btc_price_at_horizon,
    }

    break_even_price = None
    if mining_path.get("available") and buy_path_btc > 0:
        # Solve net_btc == buy_path_btc for price_at_horizon (power cost in BTC
        # terms falls as price rises, so this is a simple scalar solve).
        mined = mining_path["mined_btc"]
        power_cost = mining_path["total_power_cost"]
        if mined > buy_path_btc:
            break_even_price = power_cost / (mined - buy_path_btc) if mined != buy_path_btc else None

    return {
        "observed": {
            "btc_price": btc_price,
            "network": network_data_dict(network),
        },
        "assumptions": {
            "horizon_days": horizon_days,
            "difficulty_growth_pct_year": difficulty_growth_pct_year,
            "btc_price_at_horizon": btc_price_at_horizon,
            "electricity_usd_kwh": electricity_usd_kwh,
            "pool_fee_pct": pool_fee_pct,
            "uptime_pct": uptime_pct,
            "hardware_resale_value_usd": 0,
        },
        "buy_path": buy_path,
        "mining_path": mining_path,
        "break_even_price_at_horizon": break_even_price,
        "verdict": (
            "Mining beats buying outright"
            if mining_path.get("available") and mining_path["net_btc_after_power"] > buy_path_btc
            else "Buying outright beats mining on these assumptions"
        ),
    }


def network_data_dict(network: NetworkData) -> Dict:
    return {
        "provider": network.provider,
        "source": network.source,
        "observed_at": network.observed_at,
        "hashrate_ths": network.hashrate_ths,
        "difficulty": network.difficulty,
        "block_subsidy": network.block_subsidy,
        "block_time_seconds": network.block_time_seconds,
        "expected_blocks_per_day": network.blocks_per_day,
    }


def fleet_estimate(
    *,
    units: int,
    hashrate_ths: float,
    power_watts: float,
    hardware_cost_usd: float,
    electricity_usd_kwh: float,
    pool_fee_pct: float,
    uptime_pct: float,
    btc_price: float,
    network: NetworkData,
) -> Dict:
    per_unit = compute_estimate(
        hashrate_ths=hashrate_ths,
        power_watts=power_watts,
        electricity_usd_kwh=electricity_usd_kwh,
        pool_fee_pct=pool_fee_pct,
        uptime_pct=uptime_pct,
        btc_price=btc_price,
        hardware_cost_usd=hardware_cost_usd,
        network=network,
    )
    return {
        "units": units,
        "total_hashrate_ths": hashrate_ths * units,
        "total_power_watts": power_watts * units,
        "daily_btc": per_unit["daily_btc"] * units,
        "revenue_day": per_unit["revenue_day"] * units,
        "power_cost_day": per_unit["power_cost_day"] * units,
        "operating_profit_day": per_unit["operating_profit_day"] * units,
        "operating_profit_month": per_unit["operating_profit_month"] * units,
        "total_hardware_cost": hardware_cost_usd * units,
        "fleet_payback_days": (
            (hardware_cost_usd * units) / (per_unit["operating_profit_day"] * units)
            if per_unit["operating_profit_day"] > 0 else None
        ),
    }
