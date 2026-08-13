"""
Mining data service — mode-contract network snapshot + BTC price.

Same honesty contract as market data:
  demo mode -> labeled demo network + demo BTC price
  live mode  -> live only; if either is unavailable the mining endpoints must
                return unavailable, never a synthetic live number.
"""

from typing import Optional
from app.core.config import settings
from app.core.mining import NetworkData, NetworkProvider, BlockchainInfoProvider, DemoNetworkProvider
from app.models.schemas import PriceQuote, AssetClass
from app.services.market_data import market_data_service


class MiningDataService:
    def __init__(self) -> None:
        self._live: NetworkProvider = BlockchainInfoProvider()
        self._demo: NetworkProvider = DemoNetworkProvider()

    def is_demo(self) -> bool:
        return settings.MARKET_DATA_MODE == "demo"

    async def network(self) -> Optional[NetworkData]:
        if self.is_demo():
            return await self._demo.fetch()
        return await self._live.fetch()

    async def btc_price(self) -> Optional[PriceQuote]:
        return await market_data_service.get_quote("BTC", AssetClass.CRYPTO)

    async def btc_price_value(self) -> Optional[float]:
        quote = await self.btc_price()
        return quote.price if quote else None


mining_data_service = MiningDataService()
