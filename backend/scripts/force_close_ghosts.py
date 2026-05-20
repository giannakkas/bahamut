"""Force-close ghost positions that exist in Bahamut but not on Alpaca.
Run: railway run python backend/scripts/force_close_ghosts.py
"""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

GHOST_ASSETS = ["CRM", "UBER", "QQQ"]

def run():
    import redis
    from sqlalchemy import create_engine, text
    
    # 1. Clear from Redis
    redis_url = os.environ.get("REDIS_URL", "")
    if redis_url:
        r = redis.from_url(redis_url)
        all_pos = r.hgetall("bahamut:training:positions")
        cleared = 0
        for pid, raw in all_pos.items():
            pos = json.loads(raw)
            if pos.get("asset") in GHOST_ASSETS:
                r.hdel("bahamut:training:positions", pid)
                print(f"Redis: removed {pos['asset']} position {pid.decode()}")
                cleared += 1
        print(f"Redis: cleared {cleared} ghost positions")
    
    # 2. Close in DB
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            result = conn.execute(text("""
                UPDATE training_positions 
                SET status = 'CLOSED', exit_reason = 'MANUAL_RECONCILE', exit_time = NOW()
                WHERE asset IN ('CRM', 'UBER', 'QQQ') AND status = 'OPEN'
            """))
            conn.commit()
            print(f"DB: closed {result.rowcount} positions")

if __name__ == "__main__":
    run()
