"""
Backtest CLI Runner

Usage:
  python -m bahamut.backtesting.run --asset BTCUSD --days 90
  python -m bahamut.backtesting.run --asset EURUSD --days 180 --timeframe 1h
  python -m bahamut.backtesting.run --asset BTCUSD --days 90 --ablation
  python -m bahamut.backtesting.run --synthetic --count 1000

Options:
  --asset       Asset symbol (BTCUSD, EURUSD, etc.)
  --days        Number of days of historical data
  --timeframe   Candle interval (1h, 4h, 1day) [default: 4h]
  --profile     Trading profile (CONSERVATIVE, BALANCED, AGGRESSIVE)
  --ablation    Run ablation tests (component removal comparison)
  --synthetic   Use synthetic data (no API key needed)
  --count       Number of synthetic candles [default: 500]
  --csv         Load candles from CSV file
"""
import argparse
import asyncio
import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def main():
    parser = argparse.ArgumentParser(description="Bahamut.AI Backtesting Engine")
    parser.add_argument("--asset", default="BTCUSD", help="Asset symbol")
    parser.add_argument("--days", type=int, default=90, help="Days of history")
    parser.add_argument("--timeframe", default="4h", help="Candle interval")
    parser.add_argument("--profile", default="BALANCED", help="Trading profile")
    parser.add_argument("--ablation", action="store_true", help="Run ablation tests")
    parser.add_argument("--synthetic", action="store_true", help="Use synthetic data")
    parser.add_argument("--count", type=int, default=500, help="Synthetic candle count")
    parser.add_argument("--csv", default="", help="CSV file path")
    parser.add_argument("--sl-mult", type=float, default=2.0, help="SL ATR multiplier")
    parser.add_argument("--tp-mult", type=float, default=3.0, help="TP ATR multiplier")
    parser.add_argument("--slippage", type=float, default=5.0, help="Slippage in bps")
    parser.add_argument("--spread", type=float, default=10.0, help="Spread in bps")
    parser.add_argument("--output", default="", help="Output JSON file path")

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  BAHAMUT.AI BACKTESTING ENGINE")
    print(f"{'='*60}")
    print(f"  Asset:     {args.asset}")
    print(f"  Days:      {args.days}")
    print(f"  Timeframe: {args.timeframe}")
    print(f"  Profile:   {args.profile}")
    print(f"  SL/TP:     {args.sl_mult}x / {args.tp_mult}x ATR")
    print(f"  Slippage:  {args.slippage} bps")
    print(f"  Spread:    {args.spread} bps")
    print(f"{'='*60}\n")

    if args.ablation:
        asyncio.run(run_ablation(args))
    else:
        asyncio.run(run_single(args))


async def run_single(args):
    from bahamut.backtesting.replay import ReplayEngine, BacktestConfig
    from bahamut.backtesting.data_loader import (
        fetch_historical_candles, load_candles_from_csv, generate_synthetic_candles
    )

    # Load data
    if args.csv:
        print(f"Loading from CSV: {args.csv}")
        candles = load_candles_from_csv(args.csv)
    elif args.synthetic:
        print(f"Generating {args.count} synthetic candles...")
        base_prices = {"BTCUSD": 65000, "EURUSD": 1.085, "XAUUSD": 2600, "GBPUSD": 1.27}
        base = base_prices.get(args.asset, 100)
        vol = 0.015 if args.asset in ("BTCUSD", "ETHUSD") else 0.001
        candles = generate_synthetic_candles(base_price=base, count=args.count, volatility=vol)
    else:
        print(f"Fetching {args.days} days of {args.timeframe} data for {args.asset}...")
        candles = await fetch_historical_candles(args.asset, args.timeframe, args.days)

    print(f"Loaded {len(candles)} candles\n")

    # Configure
    asset_class_map = {
        "BTCUSD": "crypto", "ETHUSD": "crypto", "SOLUSD": "crypto",
        "EURUSD": "fx", "GBPUSD": "fx", "USDJPY": "fx",
        "XAUUSD": "commodities", "XAGUSD": "commodities",
        "AAPL": "stocks", "TSLA": "stocks", "NVDA": "stocks",
    }

    config = BacktestConfig(
        asset=args.asset,
        asset_class=asset_class_map.get(args.asset, "fx"),
        timeframe=args.timeframe.upper(),
        trading_profile=args.profile,
        sl_atr_mult=args.sl_mult,
        tp_atr_mult=args.tp_mult,
        slippage_bps=args.slippage,
        spread_bps=args.spread,
    )

    # Run
    engine = ReplayEngine(config)
    result = engine.run(candles)

    # Print results
    print_metrics(result.metrics)

    if args.output:
        output = {
            "config": {
                "asset": config.asset, "timeframe": config.timeframe,
                "sl_atr_mult": config.sl_atr_mult, "tp_atr_mult": config.tp_atr_mult,
                "slippage_bps": config.slippage_bps, "spread_bps": config.spread_bps,
            },
            "metrics": result.metrics,
            "trades": result.trades,
        }
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {args.output}")


async def run_ablation(args):
    """Run multiple backtests with components disabled for comparison."""
    from bahamut.backtesting.replay import ReplayEngine, BacktestConfig
    from bahamut.backtesting.data_loader import (
        fetch_historical_candles, generate_synthetic_candles
    )

    if args.synthetic:
        base_prices = {"BTCUSD": 65000, "EURUSD": 1.085, "XAUUSD": 2600}
        base = base_prices.get(args.asset, 100)
        vol = 0.015 if args.asset in ("BTCUSD", "ETHUSD") else 0.001
        candles = generate_synthetic_candles(base_price=base, count=args.count, volatility=vol)
    else:
        candles = await fetch_historical_candles(args.asset, args.timeframe, args.days)

    print(f"Loaded {len(candles)} candles for ablation study\n")

    asset_class_map = {
        "BTCUSD": "crypto", "EURUSD": "fx", "XAUUSD": "commodities",
    }
    ac = asset_class_map.get(args.asset, "fx")

    # Define ablation scenarios
    scenarios = {
        "FULL_SYSTEM": {},
        "NO_STRUCTURE": {"note": "EMA-only, no HH/HL market structure"},
        "WIDE_SL_3x": {"sl_atr_mult": 3.0, "tp_atr_mult": 4.5},
        "TIGHT_SL_1x": {"sl_atr_mult": 1.0, "tp_atr_mult": 2.0},
        "NO_SLIPPAGE": {"slippage_bps": 0, "spread_bps": 0},
        "HIGH_COST": {"slippage_bps": 15, "spread_bps": 25},
        "CONSERVATIVE": {"trading_profile": "CONSERVATIVE"},
        "AGGRESSIVE": {"trading_profile": "AGGRESSIVE"},
    }

    results = {}
    for name, overrides in scenarios.items():
        config = BacktestConfig(
            asset=args.asset,
            asset_class=ac,
            timeframe=args.timeframe.upper(),
            sl_atr_mult=overrides.get("sl_atr_mult", args.sl_mult),
            tp_atr_mult=overrides.get("tp_atr_mult", args.tp_mult),
            slippage_bps=overrides.get("slippage_bps", args.slippage),
            spread_bps=overrides.get("spread_bps", args.spread),
            trading_profile=overrides.get("trading_profile", args.profile),
        )
        engine = ReplayEngine(config)
        result = engine.run(candles)
        results[name] = result.metrics

    # Print comparison table
    print(f"\n{'='*80}")
    print(f"  ABLATION COMPARISON — {args.asset}")
    print(f"{'='*80}")
    print(f"{'Scenario':<20} {'Trades':>7} {'Win%':>7} {'Sharpe':>8} {'MaxDD':>8} {'Return%':>9} {'PF':>7} {'Expect':>8}")
    print(f"{'-'*80}")

    for name, m in results.items():
        print(f"{name:<20} {m['total_trades']:>7} {m['win_rate']*100:>6.1f}% {m['sharpe_ratio']:>8.3f} "
              f"{m['max_drawdown']*100:>7.2f}% {m['total_return_pct']:>8.2f}% {m['profit_factor']:>7.3f} "
              f"${m['expectancy']:>7.0f}")

    print(f"{'='*80}\n")


def print_metrics(m: dict):
    print(f"\n{'─'*50}")
    print(f"  BACKTEST RESULTS")
    print(f"{'─'*50}")
    print(f"  Total Trades:    {m['total_trades']}")
    print(f"  Wins / Losses:   {m.get('wins', 0)} / {m.get('losses', 0)}")
    print(f"  Win Rate:        {m['win_rate']*100:.1f}%")
    print(f"  Avg Win:         ${m.get('avg_win', 0):,.2f}")
    print(f"  Avg Loss:        ${m.get('avg_loss', 0):,.2f}")
    print(f"  Profit Factor:   {m['profit_factor']:.3f}")
    print(f"  Expectancy:      ${m['expectancy']:,.2f}")
    print(f"  Sharpe Ratio:    {m['sharpe_ratio']:.3f}")
    print(f"  Max Drawdown:    {m['max_drawdown']*100:.2f}%")
    print(f"  Total Return:    {m['total_return_pct']:.2f}%")
    print(f"  Final Balance:   ${m.get('final_balance', 0):,.2f}")
    if m.get("exit_reasons"):
        print(f"\n  Exit Breakdown:")
        for reason, stats in m["exit_reasons"].items():
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            print(f"    {reason:<10} {stats['count']:>4} trades, {wr:.0f}% win, ${stats['total_pnl']:>10,.2f}")
    if m.get("regime_stats"):
        print(f"\n  Regime Breakdown:")
        for regime, stats in sorted(m["regime_stats"].items()):
            wr = stats["wins"] / stats["count"] * 100 if stats["count"] > 0 else 0
            print(f"    {regime:<18} {stats['count']:>4} trades, {wr:.0f}% win, ${stats['total_pnl']:>10,.2f}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
