"""
Backfill v10 substrategy tags for historical trades.

Reclassifies trades tagged v10_mean_reversion with empty substrategy
based on their stored regime + direction:
  CRASH + SHORT → v10_crash_short
  RANGE/other + LONG → v10_range_long
  RANGE/other + SHORT → v10_range_short

Run: railway run python backend/scripts/backfill_v10_substrategy.py
Or via Postgres query tab (paste the SQL directly).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def run():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("No DATABASE_URL. Run with: railway run python backend/scripts/backfill_v10_substrategy.py")
        print("\nOr paste this SQL directly in Railway Postgres query tab:\n")
        print(BACKFILL_SQL)
        return

    from sqlalchemy import create_engine, text
    engine = create_engine(db_url)

    with engine.connect() as conn:
        # Count before
        before = conn.execute(text("""
            SELECT
                COALESCE(NULLIF(substrategy, ''), 'EMPTY') AS sub,
                COUNT(*) AS cnt
            FROM training_trades
            WHERE strategy = 'v10_mean_reversion'
            GROUP BY COALESCE(NULLIF(substrategy, ''), 'EMPTY')
            ORDER BY cnt DESC
        """)).mappings().all()
        print("BEFORE backfill:")
        for r in before:
            print(f"  {r['sub']}: {r['cnt']}")

        # Run backfill
        result = conn.execute(text(BACKFILL_SQL))
        conn.commit()
        print(f"\nRows updated: {result.rowcount}")

        # Count after
        after = conn.execute(text("""
            SELECT
                COALESCE(NULLIF(substrategy, ''), 'EMPTY') AS sub,
                COUNT(*) AS cnt
            FROM training_trades
            WHERE strategy = 'v10_mean_reversion'
            GROUP BY COALESCE(NULLIF(substrategy, ''), 'EMPTY')
            ORDER BY cnt DESC
        """)).mappings().all()
        print("\nAFTER backfill:")
        for r in after:
            print(f"  {r['sub']}: {r['cnt']}")


BACKFILL_SQL = """
UPDATE training_trades
SET substrategy = CASE
    WHEN regime = 'CRASH' AND direction = 'SHORT' THEN 'v10_crash_short'
    WHEN direction = 'LONG' THEN 'v10_range_long'
    WHEN direction = 'SHORT' THEN 'v10_range_short'
    ELSE 'v10_mean_reversion_unclassified'
END
WHERE strategy = 'v10_mean_reversion'
  AND (substrategy IS NULL OR substrategy = '' OR substrategy = 'v10_mean_reversion_unclassified')
"""


if __name__ == "__main__":
    run()
