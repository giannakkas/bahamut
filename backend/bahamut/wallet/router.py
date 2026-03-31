"""
Bahamut.AI — User Wallet API

Persistent wallet (PostgreSQL) for trader balances, allocations, and transaction history.
Replaces localStorage-based wallet that was lost on cache clear.
"""
import structlog
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from bahamut.auth.router import get_current_user
from bahamut.db.query import run_query, run_query_one, run_transaction, ensure_table

logger = structlog.get_logger()
router = APIRouter()

# ── Schema ──

WALLET_TABLE = """
CREATE TABLE IF NOT EXISTS user_wallets (
    user_id TEXT PRIMARY KEY,
    balance REAL NOT NULL DEFAULT 0,
    allocation REAL NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'demo',
    updated_at TIMESTAMPTZ DEFAULT NOW()
)
"""

TRANSACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    allocation_after REAL NOT NULL,
    mode TEXT NOT NULL DEFAULT 'demo',
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""

def _ensure_tables():
    try:
        ensure_table(WALLET_TABLE)
        ensure_table(TRANSACTIONS_TABLE)
    except Exception as e:
        logger.error("wallet_tables_failed", error=str(e))

_ensure_tables()


# ── Models ──

class DepositRequest(BaseModel):
    amount: float
    mode: str = "demo"

class AllocationRequest(BaseModel):
    amount: float
    mode: str = "demo"


# ── Endpoints ──

@router.get("")
async def get_wallet(user=Depends(get_current_user)):
    """Get user's wallet state + recent transaction history."""
    uid = str(user.id)

    wallet = run_query_one(
        "SELECT balance, allocation, mode, updated_at FROM user_wallets WHERE user_id = :uid",
        {"uid": uid}
    )

    if not wallet:
        wallet = {"balance": 0, "allocation": 0, "mode": "demo", "updated_at": None}

    transactions = run_query(
        """SELECT type, amount, balance_after, allocation_after, mode, created_at
           FROM wallet_transactions WHERE user_id = :uid
           ORDER BY created_at DESC LIMIT 50""",
        {"uid": uid}
    )

    return {
        "balance": wallet["balance"],
        "allocation": wallet["allocation"],
        "mode": wallet.get("mode", "demo"),
        "updated_at": str(wallet.get("updated_at", "")),
        "transactions": [
            {
                "type": t["type"],
                "amount": t["amount"],
                "balance_after": t["balance_after"],
                "allocation_after": t["allocation_after"],
                "mode": t["mode"],
                "timestamp": str(t["created_at"]),
            }
            for t in transactions
        ],
    }


@router.post("/deposit")
async def deposit(req: DepositRequest, user=Depends(get_current_user)):
    """Add funds to wallet. Demo max $100K."""
    uid = str(user.id)
    amount = max(0, req.amount)

    wallet = run_query_one(
        "SELECT balance, allocation FROM user_wallets WHERE user_id = :uid",
        {"uid": uid}
    )

    current_balance = wallet["balance"] if wallet else 0
    current_alloc = wallet["allocation"] if wallet else 0

    # Demo cap at 100K
    if req.mode == "demo":
        amount = min(amount, 100000 - current_balance)

    if amount <= 0:
        return {"error": "No funds to add", "balance": current_balance}

    new_balance = round(current_balance + amount, 2)

    # Auto-set allocation if it was 0
    new_alloc = current_alloc
    if current_alloc == 0:
        new_alloc = new_balance

    now = datetime.now(timezone.utc).isoformat()

    if wallet:
        run_transaction(
            """UPDATE user_wallets SET balance = :bal, allocation = :alloc,
               mode = :mode, updated_at = :now WHERE user_id = :uid""",
            {"bal": new_balance, "alloc": new_alloc, "mode": req.mode, "now": now, "uid": uid}
        )
    else:
        run_transaction(
            """INSERT INTO user_wallets (user_id, balance, allocation, mode, updated_at)
               VALUES (:uid, :bal, :alloc, :mode, :now)""",
            {"uid": uid, "bal": new_balance, "alloc": new_alloc, "mode": req.mode, "now": now}
        )

    # Record transaction
    run_transaction(
        """INSERT INTO wallet_transactions (user_id, type, amount, balance_after, allocation_after, mode)
           VALUES (:uid, 'deposit', :amt, :bal, :alloc, :mode)""",
        {"uid": uid, "amt": amount, "bal": new_balance, "alloc": new_alloc, "mode": req.mode}
    )

    logger.info("wallet_deposit", user_id=uid, amount=amount, new_balance=new_balance)
    return {"balance": new_balance, "allocation": new_alloc, "deposited": amount}


@router.post("/allocation")
async def set_allocation(req: AllocationRequest, user=Depends(get_current_user)):
    """Set trading allocation. Cannot exceed balance."""
    uid = str(user.id)

    wallet = run_query_one(
        "SELECT balance, allocation FROM user_wallets WHERE user_id = :uid",
        {"uid": uid}
    )

    if not wallet:
        return {"error": "No wallet found. Deposit funds first."}

    new_alloc = round(min(max(0, req.amount), wallet["balance"]), 2)
    now = datetime.now(timezone.utc).isoformat()

    run_transaction(
        "UPDATE user_wallets SET allocation = :alloc, mode = :mode, updated_at = :now WHERE user_id = :uid",
        {"alloc": new_alloc, "mode": req.mode, "now": now, "uid": uid}
    )

    run_transaction(
        """INSERT INTO wallet_transactions (user_id, type, amount, balance_after, allocation_after, mode)
           VALUES (:uid, 'allocation', :amt, :bal, :alloc, :mode)""",
        {"uid": uid, "amt": new_alloc, "bal": wallet["balance"], "alloc": new_alloc, "mode": req.mode}
    )

    logger.info("wallet_allocation", user_id=uid, allocation=new_alloc)
    return {"balance": wallet["balance"], "allocation": new_alloc}
