"""
Bahamut Performance Analysis — Run on Railway or locally with DATABASE_URL set.

Usage:
  python backend/scripts/performance_report.py

Or on Railway:
  railway run python backend/scripts/performance_report.py
"""
import os
import sys

# Add backend to path so imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

def run():
    from sqlalchemy import create_engine, text
    
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set. Run with: railway run python backend/scripts/performance_report.py")
        sys.exit(1)
    
    engine = create_engine(db_url)
    
    queries = {
        "QUERY 1 — Strategy Performance (non-debug only)": """
            SELECT 
                strategy,
                COUNT(*) AS trades,
                SUM(CASE WHEN pnl > 0.50 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl < -0.50 THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN ABS(pnl) <= 0.50 THEN 1 ELSE 0 END) AS flats,
                ROUND(AVG(pnl)::numeric, 2) AS avg_pnl,
                ROUND(SUM(pnl)::numeric, 2) AS total_pnl,
                ROUND(100.0 * SUM(CASE WHEN pnl > 0.50 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS win_rate_pct
            FROM training_trades 
            WHERE execution_type != 'debug_exploration'
            GROUP BY strategy
            ORDER BY total_pnl DESC
        """,
        "QUERY 2 — Exit Reason Breakdown per Strategy": """
            SELECT 
                strategy,
                exit_reason,
                COUNT(*) AS trades,
                ROUND(AVG(pnl)::numeric, 2) AS avg_pnl,
                ROUND(AVG(bars_held)::numeric, 1) AS avg_bars
            FROM training_trades 
            WHERE execution_type != 'debug_exploration'
            GROUP BY strategy, exit_reason
            ORDER BY strategy, exit_reason
        """,
        "QUERY 3 — Asset Class × Strategy Matrix": """
            SELECT 
                asset_class,
                strategy,
                COUNT(*) AS trades,
                ROUND(100.0 * SUM(CASE WHEN pnl > 0.50 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS win_rate_pct,
                ROUND(SUM(pnl)::numeric, 2) AS total_pnl
            FROM training_trades 
            WHERE execution_type != 'debug_exploration'
            GROUP BY asset_class, strategy
            ORDER BY total_pnl DESC
        """,
        "QUERY 4 — Rolling 7d vs All-Time": """
            SELECT 
                'last_7d' AS period, COUNT(*) AS trades,
                ROUND(AVG(pnl)::numeric, 2) AS avg_pnl,
                ROUND(100.0 * SUM(CASE WHEN pnl > 0.50 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS wr_pct
            FROM training_trades 
            WHERE exit_time::timestamp > NOW() - INTERVAL '7 days' 
              AND execution_type != 'debug_exploration'
            UNION ALL
            SELECT 
                'all_time' AS period, COUNT(*) AS trades,
                ROUND(AVG(pnl)::numeric, 2) AS avg_pnl,
                ROUND(100.0 * SUM(CASE WHEN pnl > 0.50 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS wr_pct
            FROM training_trades 
            WHERE execution_type != 'debug_exploration'
        """,
        "QUERY 5 — TIMEOUT Dominance (combos with 10+ trades)": """
            SELECT 
                strategy,
                asset_class,
                ROUND(100.0 * SUM(CASE WHEN exit_reason='TIMEOUT' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS timeout_pct,
                ROUND(100.0 * SUM(CASE WHEN exit_reason='SL' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS sl_pct,
                ROUND(100.0 * SUM(CASE WHEN exit_reason='TP' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS tp_pct,
                COUNT(*) AS trades
            FROM training_trades 
            WHERE execution_type != 'debug_exploration'
            GROUP BY strategy, asset_class
            HAVING COUNT(*) >= 10
            ORDER BY timeout_pct DESC
        """,
        "QUERY 6 — Top/Bottom 10 Asset+Strategy Combos (non-debug, 3+ trades)": """
            (SELECT asset, strategy, direction, COUNT(*) AS trades,
                ROUND(SUM(pnl)::numeric, 2) AS total_pnl,
                ROUND(AVG(pnl)::numeric, 2) AS avg_pnl,
                ROUND(100.0 * SUM(CASE WHEN pnl > 0.50 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS wr_pct
            FROM training_trades 
            WHERE execution_type != 'debug_exploration'
            GROUP BY asset, strategy, direction
            HAVING COUNT(*) >= 3
            ORDER BY total_pnl DESC LIMIT 10)
            UNION ALL
            (SELECT asset, strategy, direction, COUNT(*) AS trades,
                ROUND(SUM(pnl)::numeric, 2) AS total_pnl,
                ROUND(AVG(pnl)::numeric, 2) AS avg_pnl,
                ROUND(100.0 * SUM(CASE WHEN pnl > 0.50 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1) AS wr_pct
            FROM training_trades 
            WHERE execution_type != 'debug_exploration'
            GROUP BY asset, strategy, direction
            HAVING COUNT(*) >= 3
            ORDER BY total_pnl ASC LIMIT 10)
        """,
        "QUERY 7 — SL Distance Distribution for Stocks (non-debug)": """
            SELECT 
                asset, strategy, direction,
                ROUND(entry_price::numeric, 2) AS entry,
                ROUND(stop_price::numeric, 2) AS stop,
                ROUND(100.0 * ABS(entry_price - stop_price) / NULLIF(entry_price, 0), 2) AS sl_pct,
                ROUND(pnl::numeric, 2) AS pnl,
                exit_reason,
                entry_time::date AS date
            FROM training_trades
            WHERE asset_class = 'stock'
              AND execution_type != 'debug_exploration'
            ORDER BY entry_time DESC
            LIMIT 30
        """,
    }
    
    print("=" * 80)
    print("BAHAMUT PERFORMANCE REPORT — Non-Debug Trades Only")
    print("=" * 80)
    
    flags = []
    
    with engine.connect() as conn:
        for title, sql in queries.items():
            print(f"\n{'─' * 80}")
            print(f"  {title}")
            print(f"{'─' * 80}")
            try:
                rows = conn.execute(text(sql)).mappings().all()
                if not rows:
                    print("  (no data)")
                    continue
                
                # Print header
                cols = list(rows[0].keys())
                header = "  " + "  ".join(f"{c:>12}" for c in cols)
                print(header)
                print("  " + "-" * len(header))
                
                for row in rows:
                    line = "  " + "  ".join(f"{str(row[c]):>12}" for c in cols)
                    print(line)
                    
                    # Flag checks for Query 1
                    if title.startswith("QUERY 1"):
                        trades = int(row.get("trades", 0))
                        wr = float(row.get("win_rate_pct", 0) or 0)
                        pnl = float(row.get("total_pnl", 0) or 0)
                        strat = row.get("strategy", "?")
                        if trades > 20 and wr < 45:
                            flags.append(f"⚠️  {strat}: WR {wr}% with {trades} trades (underperforming)")
                        if pnl < -500:
                            flags.append(f"🔴 {strat}: total PnL ${pnl} (systematic loss)")
                    
                    # Flag checks for Query 5
                    if title.startswith("QUERY 5"):
                        to_pct = float(row.get("timeout_pct", 0) or 0)
                        strat = row.get("strategy", "?")
                        ac = row.get("asset_class", "?")
                        trades = int(row.get("trades", 0))
                        if to_pct > 75:
                            flags.append(f"⏰ {strat}+{ac}: {to_pct}% TIMEOUT rate ({trades} trades) — SL/TP calibration suspect")
                
            except Exception as e:
                print(f"  ERROR: {e}")
    
    # Summary
    print(f"\n{'=' * 80}")
    print("FLAGS & ALERTS")
    print(f"{'=' * 80}")
    if flags:
        for f in flags:
            print(f"  {f}")
    else:
        print("  ✅ No flags triggered")
    
    print(f"\n{'=' * 80}")
    print("END REPORT")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    run()
