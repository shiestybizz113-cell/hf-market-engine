from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import settings

client: AsyncIOMotorClient | None = None
db: AsyncIOMotorDatabase | None = None


async def connect_to_mongo():
    global client, db
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client[settings.MONGODB_DB]

    # Core user/product indexes.
    await db.users.create_index("email", unique=True)
    await db.watchlist.create_index([("user_id", 1), ("symbol", 1)], unique=True)
    await db.strategies.create_index([("user_id", 1), ("name", 1)])
    await db.paper_trades.create_index([("user_id", 1), ("status", 1)])
    await db.portfolio.create_index([("user_id", 1), ("symbol", 1)])
    await db.journal.create_index([("user_id", 1), ("trade_date", -1)])
    await db.execution_orders.create_index([("user_id", 1), ("created_at", -1)])

    # Evidence fabric: immutable facts + raw provider snapshots.
    await db.evidence_facts.create_index(
        [("domain", 1), ("metric", 1), ("subject_id", 1), ("user_id", 1), ("observed_at", -1)]
    )
    await db.evidence_facts.create_index("evidence_id", unique=True)
    await db.evidence_facts.create_index([("user_id", 1), ("observed_at", -1)])
    await db.evidence_facts.create_index([("domain", 1), ("metric", 1), ("region", 1), ("observed_at", -1)])

    await db.provider_snapshots.create_index("snapshot_id", unique=True)
    await db.provider_snapshots.create_index([("domain", 1), ("provider", 1), ("observed_at", -1)])

    # Customer assets/current operator state.
    await db.assets.create_index([("user_id", 1), ("status", 1)])
    await db.assets.create_index([("user_id", 1), ("asset_type", 1)])
    await db.assets.create_index([("user_id", 1), ("asset_id", 1)], unique=True)

    # Decision receipts/proof traversal.
    await db.mining_receipts.create_index([("user_id", 1), ("observed_at", -1)])
    await db.mining_receipts.create_index([("user_id", 1), ("analysis_type", 1), ("observed_at", -1)])
    await db.mining_receipts.create_index("evidence_ids")
    await db.analysis_receipts.create_index([("user_id", 1), ("generated_at", -1)])

    # Force an actual connection check during startup instead of accepting a lazy
    # Motor client and discovering a bad credential only after traffic arrives.
    await db.command("ping")
    print(f"Connected to MongoDB: {settings.MONGODB_DB}")


async def close_mongo_connection():
    global client, db
    if client:
        client.close()
        client = None
        db = None
        print("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    if db is None:
        raise RuntimeError("Database not initialized")
    return db
