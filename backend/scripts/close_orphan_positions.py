"""Close orphaned Binance Futures positions — positions open on the exchange
with NO corresponding local record in Bahamut.

These are the residue of the pre-2026-07-18 phantom-close bug: the engine booked
a trade as closed locally while the real position stayed open on the exchange.
The bug is fixed (commit d2de3da), so no new orphans are created — this only
cleans up the historical leftovers.

SAFETY DESIGN
  * DRY RUN by default. Nothing is sent to the exchange without --execute.
  * Locally-TRACKED positions are excluded. Only positions with no local record
    are eligible, so live managed trades are never touched.
  * Closes use reduceOnly=True, so an order can only ever flatten a position,
    never open a new one.
  * Refuses to run against a non-demo/mainnet base URL unless --allow-mainnet
    is passed, so it cannot accidentally touch a real-money account.

USAGE
    python scripts/close_orphan_positions.py              # dry run (safe)
    python scripts/close_orphan_positions.py --execute    # actually close
"""
import argparse
import os
import sys

# Python puts THIS file's directory (scripts/) on sys.path, not the backend root,
# so `import bahamut` fails when run as `python scripts/close_orphan_positions.py`.
# Add the backend root explicitly so the script works from any working directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="Actually submit close orders (default is dry run).")
    ap.add_argument("--allow-mainnet", action="store_true",
                    help="Permit running against a non-demo/testnet endpoint.")
    args = ap.parse_args()

    from bahamut.execution.binance_futures import (
        get_positions, get_account, place_market_order, BASE_URL, _to_symbol,
        _configured)

    if not _configured():
        print("ERROR: Binance Futures not configured (missing API keys).")
        return 2

    # ── Guard: never touch a real-money account by accident ──
    is_demo = ("demo" in BASE_URL.lower()) or ("testnet" in BASE_URL.lower())
    print(f"Endpoint: {BASE_URL}  ({'DEMO/TESTNET' if is_demo else 'MAINNET'})")
    if not is_demo and not args.allow_mainnet:
        print("REFUSING: endpoint is not demo/testnet. Re-run with --allow-mainnet "
              "only if you are certain.")
        return 2

    # ── Verify connectivity: an empty position list must not be mistaken for
    # "no positions" when the API is simply failing. ──
    if get_account() is None:
        print("ERROR: cannot read account — aborting rather than acting blind.")
        return 2

    broker = get_positions()
    if not broker:
        print("No open positions on the exchange. Nothing to do.")
        return 0

    # ── Build the set of symbols Bahamut is actively tracking. These are OFF
    # LIMITS: they are live managed trades, not orphans. ──
    tracked: set[str] = set()
    try:
        from bahamut.trading.engine import _load_positions
        for p in _load_positions():
            try:
                tracked.add(_to_symbol(p.asset))
            except Exception:
                pass
    except Exception as e:
        print(f"ERROR: could not load local positions ({str(e)[:120]}).")
        print("Refusing to continue — without the tracked list this could close "
              "a live managed trade.")
        return 2

    print(f"Locally tracked (protected): {sorted(tracked) or 'none'}")

    orphans = [p for p in broker if p.get("symbol") not in tracked]
    protected = [p for p in broker if p.get("symbol") in tracked]

    print(f"\nExchange positions: {len(broker)}  |  "
          f"protected: {len(protected)}  |  orphans: {len(orphans)}")

    if not orphans:
        print("No orphans. Nothing to do.")
        return 0

    print("\nOrphans eligible for closing:")
    for p in orphans:
        print(f"  {p['symbol']:12} {p['side']:5} qty={p['qty']:<12} "
              f"entry={p.get('entry_price')} uPnL={p.get('unrealized_pnl')}")

    if not args.execute:
        print("\n[DRY RUN] Nothing was sent to the exchange.")
        print("To actually close these, re-run with:  --execute")
        return 0

    print("\nSubmitting reduceOnly close orders...")
    ok = failed = 0
    for p in orphans:
        sym, side, qty = p["symbol"], p["side"], p["qty"]
        close_side = "SELL" if side == "LONG" else "BUY"
        try:
            res = place_market_order(sym, close_side, qty, reduce_only=True)
            if res and not res.get("error"):
                ok += 1
                print(f"  CLOSED  {sym:12} {close_side} {qty} "
                      f"-> order {res.get('order_id')} status={res.get('status')}")
            else:
                failed += 1
                print(f"  FAILED  {sym:12} {res}")
        except Exception as e:
            failed += 1
            print(f"  FAILED  {sym:12} {type(e).__name__}: {str(e)[:120]}")

    print(f"\nDone. closed={ok} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
