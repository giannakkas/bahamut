#!/usr/bin/env python3
"""
Bahamut.AI — Phantom Exposure Fix Script (one-time)

Diagnoses and fixes the state where:
  - paper_positions has rows with status='OPEN'
  - But no trades are actually open (stale/orphaned positions)
  - This causes gross_exposure to be wildly inflated (e.g. 373%)

Run:
  cd backend && python scripts/fix_phantom_exposure.py

Pass --dry-run to just diagnose without changing anything.
Pass --force to actually close the orphaned positions.
"""
import os
import sys
import argparse

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    parser = argparse.ArgumentParser(description="Fix phantom exposure from orphaned positions")
    parser.add_argument("--dry-run", action="store_true", help="Diagnose only, don't change anything")
    parser.add_argument("--force", action="store_true", help="Actually close orphaned positions")
    args = parser.parse_args()

    if not args.dry_run and not args.force:
        print("⚠️  Pass --dry-run to diagnose or --force to fix.")
        print("   Example: python scripts/fix_phantom_exposure.py --dry-run")
        sys.exit(1)

    from sqlalchemy import create_engine, text
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL not set")
        sys.exit(1)

    engine = create_engine(db_url)

    with engine.connect() as conn:
        # 1. Get portfolio balance
        bal = conn.execute(text(
            "SELECT current_balance FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
        )).scalar()
        print(f"\n📊 Portfolio balance: ${bal:,.2f}" if bal else "\n❌ No SYSTEM_DEMO portfolio found")

        # 2. Count and list all OPEN positions
        open_rows = conn.execute(text("""
            SELECT id, asset, direction, position_value, risk_amount, status,
                   entry_price, current_price, opened_at, execution_mode
            FROM paper_positions WHERE status = 'OPEN'
            ORDER BY opened_at
        """)).mappings().all()

        print(f"\n📋 Open positions in DB: {len(open_rows)}")

        if not open_rows:
            print("✅ No open positions — no phantom exposure possible.")
            return

        total_value = 0.0
        total_risk = 0.0
        for r in open_rows:
            pv = float(r["position_value"])
            ra = float(r["risk_amount"])
            total_value += pv
            total_risk += ra
            age = ""
            if r["opened_at"]:
                from datetime import datetime, timezone
                try:
                    opened = r["opened_at"]
                    if opened.tzinfo is None:
                        opened = opened.replace(tzinfo=timezone.utc)
                    age_hours = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
                    age = f" ({age_hours:.1f}h ago)"
                except Exception:
                    pass

            print(f"  #{r['id']:4d}  {r['asset']:10s}  {r['direction']:5s}  "
                  f"val=${pv:>10,.2f}  risk=${ra:>8,.2f}  "
                  f"mode={r.get('execution_mode', 'STRICT'):12s}  "
                  f"opened={r['opened_at']}{age}")

        gross_pct = (total_value / bal * 100) if bal else 0
        print(f"\n📈 Total position value: ${total_value:,.2f}")
        print(f"📈 Total risk: ${total_risk:,.2f}")
        print(f"📈 Gross exposure: {gross_pct:.1f}%")

        if gross_pct > 100:
            print(f"\n🚨 PHANTOM EXPOSURE DETECTED: {gross_pct:.1f}% with {len(open_rows)} positions")

        # 3. Check v7_orders for comparison
        try:
            v7_open = conn.execute(text(
                "SELECT COUNT(*) FROM v7_orders WHERE status = 'OPEN'"
            )).scalar()
            print(f"\n📋 v7_orders OPEN count: {v7_open}")
            if v7_open == 0 and len(open_rows) > 0:
                print("🚨 MISMATCH: v7_orders has 0 open but paper_positions has "
                      f"{len(open_rows)} open — these are orphans!")
        except Exception:
            print("ℹ️  v7_orders table not found (may not be in use)")

        if args.dry_run:
            print("\n🔍 DRY RUN — no changes made. Use --force to fix.")
            return

        # 4. Force-close all orphaned positions
        print(f"\n🔧 Force-closing {len(open_rows)} orphaned positions...")

        closed_count = conn.execute(text("""
            UPDATE paper_positions
            SET status = 'CLOSED_ORPHAN_FIX',
                closed_at = NOW(),
                exit_price = COALESCE(current_price, entry_price),
                realized_pnl = 0,
                realized_pnl_pct = 0
            WHERE status = 'OPEN'
            RETURNING id
        """)).rowcount
        conn.commit()

        print(f"✅ Closed {closed_count} orphaned positions")

        # 5. Verify
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM paper_positions WHERE status = 'OPEN'"
        )).scalar()
        print(f"📋 Remaining OPEN positions: {remaining}")

        if remaining == 0:
            print("✅ Phantom exposure eliminated. System should now show 0% exposure.")
        else:
            print(f"⚠️  Still {remaining} OPEN positions — investigate manually.")


if __name__ == "__main__":
    main()
