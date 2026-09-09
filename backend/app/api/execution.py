"""
Execution API — Phase 1 paper only. Phase 2 live routes will reuse the same surface.
"""


from fastapi import APIRouter, Depends, HTTPException

from app.core.plans import require_feature
from app.engines.execution_engine import ALGO_CATALOG, execution_engine
from app.models.execution import (
    ExecutionAlgoConfig,
    ExecutionAlgoInfo,
    ExecutionAnalytics,
    ExecutionUrgency,
    ParentOrder,
    ParentOrderCreate,
)
from app.models.schemas import AssetClass

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("/algos", response_model=list[ExecutionAlgoInfo])
async def list_execution_algos():
    """Educational catalog of supported execution strategies."""
    return ALGO_CATALOG


@router.get("/algos/{algo_type}", response_model=ExecutionAlgoInfo)
async def get_algo_info(algo_type: str):
    for a in ALGO_CATALOG:
        if a.algo_type.value == algo_type:
            return a
    raise HTTPException(404, "Unknown algo type")


@router.post("/recommend", response_model=ExecutionAlgoConfig)
async def recommend_algo(
    asset: str,
    asset_class: AssetClass = AssetClass.CRYPTO,
    side: str = "buy",
    quantity: float = 1.0,
    urgency: ExecutionUrgency = ExecutionUrgency.MEDIUM,
    current_user=Depends(require_feature("execution_sim")),
):
    return await execution_engine.recommend_algo(asset, asset_class, side, quantity, urgency)


@router.post("/orders", response_model=ParentOrder)
async def submit_order(payload: ParentOrderCreate, current_user=Depends(require_feature("execution_sim"))):
    """
    Submit a parent order.
    Phase 1: paper_mode must be True (enforced by engine).
    """
    try:
        # Force paper in Phase 1
        payload.paper_mode = True
        return await execution_engine.submit_parent_order(current_user["_id"], payload)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/orders", response_model=list[ParentOrder])
async def list_orders(status: str | None = None, current_user=Depends(require_feature("execution_sim"))):
    return await execution_engine.list_parent_orders(current_user["_id"], status)


@router.get("/orders/{parent_id}", response_model=ParentOrder)
async def get_order(parent_id: str, current_user=Depends(require_feature("execution_sim"))):
    order = await execution_engine.get_parent_order(current_user["_id"], parent_id)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.post("/orders/{parent_id}/cancel", response_model=ParentOrder)
async def cancel_order(parent_id: str, current_user=Depends(require_feature("execution_sim"))):
    try:
        return await execution_engine.cancel_parent_order(current_user["_id"], parent_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/orders/{parent_id}/analytics", response_model=ExecutionAnalytics)
async def order_analytics(parent_id: str, current_user=Depends(require_feature("execution_sim"))):
    analytics = await execution_engine.get_analytics(current_user["_id"], parent_id)
    if not analytics:
        raise HTTPException(404, "Analytics not available")
    return analytics
