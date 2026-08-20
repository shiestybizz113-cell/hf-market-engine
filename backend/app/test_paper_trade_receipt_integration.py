"""
Integration test for paper trade receipt creation.
Tests that:
1. A paper trade can be opened and closed
2. A receipt is created and persisted
3. The receipt can be retrieved and verified
"""

import asyncio
import uuid
from datetime import datetime, timezone
from app.engines.paper_trading import paper_trading_engine
from app.services.receipts.paper_trade_receipt_service import paper_trade_receipt_service
from app.core.database import get_db
from app.models.schemas import PaperTradeCreate, AssetClass

async def test_paper_trade_receipt_integration():
    """Test the complete paper trade → receipt → verification flow."""
    print("Starting paper trade receipt integration test...")
    
    # Use a fixed user ID for testing
    test_user_id = f"test-user-{uuid.uuid4().hex[:8]}"
    print(f"Test user ID: {test_user_id}")
    
    # Create a paper trade
    trade_payload = PaperTradeCreate(
        asset="AAPL",
        asset_class=AssetClass.EQUITY,
        direction="long",
        quantity=10,
        entry_price=150.0,
        notes="Test trade for receipt integration"
    )
    
    print("Opening paper trade...")
    opened_trade = await paper_trading_engine.open_trade(test_user_id, trade_payload)
    print(f"Opened trade: {opened_trade.id}")
    assert opened_trade.status == "open"
    assert opened_trade.asset == "AAPL"
    assert opened_trade.quantity == 10
    
    # Close the paper trade (this should trigger receipt creation)
    print("Closing paper trade...")
    closed_trade = await paper_trading_engine.close_trade(test_user_id, opened_trade.id)
    print(f"Closed trade: {closed_trade.id}")
    print(f"  Exit price: {closed_trade.exit_price}")
    print(f"  Realized P&L: {closed_trade.realized_pnl}")
    assert closed_trade.status == "closed"
    assert closed_trade.exit_price is not None
    assert closed_trade.realized_pnl is not None
    
    # Give a moment for async operations to complete
    await asyncio.sleep(0.1)
    
    # Retrieve receipts for the user
    print("Retrieving receipts for user...")
    receipts = paper_trade_receipt_service.get_receipts_for_user(test_user_id, limit=10)
    print(f"Found {len(receipts)} receipts")
    
    assert len(receipts) > 0, "No receipts were created for the paper trade"
    
    # Get the most recent receipt
    latest_receipt = receipts[0]
    print(f"Latest receipt ID: {latest_receipt.receipt_id}")
    print(f"  Action type: {latest_receipt.action.action_type}")
    print(f"  Symbol: {latest_receipt.action.payload.get('symbol')}")
    print(f"  Quantity: {latest_receipt.action.payload.get('qty')}")
    print(f"  Exit price: {latest_receipt.claimed_outcome.outcome_payload.get('fill_price')}")
    print(f"  P&L: {latest_receipt.claimed_outcome.outcome_payload.get('pnl')}")
    
    # Verify the receipt
    print("Verifying receipt...")
    is_valid, reason = paper_trade_receipt_service.verify_receipt(latest_receipt)
    print(f"  Verification result: {is_valid}")
    print(f"  Reason: {reason}")
    
    assert is_valid, f"Receipt verification failed: {reason}"
    assert latest_receipt.action.action_type == "trade_order"
    assert latest_receipt.action.payload.get("symbol") == "AAPL"
    assert latest_receipt.action.payload.get("qty") == 10
    
    # Test that we can retrieve the receipt by ID
    print("Testing receipt retrieval by ID...")
    retrieved_receipt = paper_trade_receipt_service.get_receipt_by_id(latest_receipt.receipt_id)
    assert retrieved_receipt is not None, "Failed to retrieve receipt by ID"
    assert retrieved_receipt.receipt_id == latest_receipt.receipt_id
    print(f"Successfully retrieved receipt by ID: {retrieved_receipt.receipt_id}")
    
    print("\n✅ Integration test passed!")
    print("✅ Paper trade created and closed")
    print("✅ Receipt generated and persisted")
    print("✅ Receipt retrieved and verified")
    print("✅ HF trade can be traced to receipt without changing order model")
    
    return True

if __name__ == "__main__":
    # Run the test
    success = asyncio.run(test_paper_trade_receipt_integration())
    if success:
        print("\n🎉 All tests passed! The HF → Receipt Graph integration is working.")
    else:
        print("\n❌ Tests failed!")
        exit(1)
