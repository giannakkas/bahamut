"""
Bahamut.AI Position Registry — fast snapshot of open positions.

Loads from paper_positions, enriches with asset_class/theme.
Used by exposure, correlation, and scoring engines.
"""
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()

ASSET_CLASS_MAP = {
    "EURUSD": "fx", "GBPUSD": "fx", "USDJPY": "fx", "AUDUSD": "fx",
    "USDCAD": "fx", "USDCHF": "fx", "NZDUSD": "fx", "EURGBP": "fx",
    "EURJPY": "fx", "GBPJPY": "fx",
    "BTCUSD": "crypto", "ETHUSD": "crypto", "SOLUSD": "crypto",
    "BNBUSD": "crypto", "XRPUSD": "crypto", "ADAUSD": "crypto",
    "DOGEUSD": "crypto", "AVAXUSD": "crypto", "DOTUSD": "crypto",
    "LINKUSD": "crypto", "MATICUSD": "crypto",
    "XAUUSD": "commodities", "XAGUSD": "commodities",
    "WTIUSD": "commodities", "BCOUSD": "commodities",
    "AAPL": "stocks", "MSFT": "stocks", "GOOGL": "stocks",
    "AMZN": "stocks", "NVDA": "stocks", "META": "stocks",
    "TSLA": "stocks", "JPM": "stocks", "V": "stocks",
    "AMD": "stocks", "NFLX": "stocks", "CRM": "stocks",
}

# Themes: assets that move together or share macro drivers
THEME_MAP = {
    "usd_strength": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF"],
    "jpy_crosses": ["USDJPY", "EURJPY", "GBPJPY"],
    "big_tech": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"],
    "risk_assets": ["BTCUSD", "ETHUSD", "SOLUSD", "TSLA", "NVDA"],
    "safe_haven": ["XAUUSD", "USDJPY", "USDCHF"],
    "energy": ["WTIUSD", "BCOUSD"],
    "defi_alt": ["SOLUSD", "AVAXUSD", "DOTUSD", "LINKUSD", "MATICUSD"],
    "financials": ["JPM", "V"],
}


@dataclass
class OpenPosition:
    id: int
    asset: str
    direction: str
    position_value: float
    risk_amount: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    consensus_score: float
    asset_class: str = ""
    themes: list = field(default_factory=list)


@dataclass
class PortfolioSnapshot:
    positions: list = field(default_factory=list)
    balance: float = 100000.0
    total_position_value: float = 0.0
    total_risk: float = 0.0

    @property
    def position_count(self):
        return len(self.positions)

    def assets(self):
        return [p.asset for p in self.positions]

    def by_asset_class(self):
        classes = {}
        for p in self.positions:
            classes.setdefault(p.asset_class, []).append(p)
        return classes

    def by_theme(self):
        themes = {}
        for p in self.positions:
            for t in p.themes:
                themes.setdefault(t, []).append(p)
        return themes

    def by_direction(self):
        return {
            "LONG": [p for p in self.positions if p.direction == "LONG"],
            "SHORT": [p for p in self.positions if p.direction == "SHORT"],
        }


def load_portfolio_snapshot() -> PortfolioSnapshot:
    """Load current open positions from DB into a fast snapshot.
    
    Includes sanity checks:
      - Only loads status='OPEN' positions
      - Cross-checks position_count vs total_position_value
      - Logs CRITICAL if phantom exposure detected (value > 0 with 0 positions)
    """
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            bal_row = conn.execute(text(
                "SELECT current_balance FROM paper_portfolios WHERE name = 'SYSTEM_DEMO'"
            )).scalar()
            balance = float(bal_row) if bal_row else 100000.0

            rows = conn.execute(text("""
                SELECT id, asset, direction, position_value, risk_amount,
                       entry_price, current_price, unrealized_pnl, consensus_score
                FROM paper_positions WHERE status = 'OPEN'
                ORDER BY opened_at
            """)).mappings().all()

            positions = []
            total_val = 0.0
            total_risk = 0.0
            for r in rows:
                asset = r["asset"]
                ac = ASSET_CLASS_MAP.get(asset, "other")
                themes = [t for t, assets in THEME_MAP.items() if asset in assets]
                pos_value = float(r["position_value"])

                # Skip positions with zero or negative value (data integrity guard)
                if pos_value <= 0:
                    logger.warning("invalid_position_value_skipped",
                                   position_id=r["id"], asset=asset,
                                   position_value=pos_value)
                    continue

                p = OpenPosition(
                    id=r["id"], asset=asset, direction=r["direction"],
                    position_value=pos_value,
                    risk_amount=float(r["risk_amount"]),
                    entry_price=float(r["entry_price"]),
                    current_price=float(r["current_price"] or r["entry_price"]),
                    unrealized_pnl=float(r["unrealized_pnl"] or 0),
                    consensus_score=float(r["consensus_score"]),
                    asset_class=ac, themes=themes,
                )
                positions.append(p)
                total_val += p.position_value
                total_risk += p.risk_amount

            snapshot = PortfolioSnapshot(
                positions=positions, balance=balance,
                total_position_value=total_val, total_risk=total_risk,
            )

            # ── Sanity cross-check ──
            if snapshot.position_count == 0 and total_val > 0:
                logger.critical("phantom_exposure_at_load",
                                db_rows=len(rows), filtered_positions=0,
                                total_position_value=total_val,
                                action="forcing_zero")
                snapshot.total_position_value = 0.0
                snapshot.total_risk = 0.0

            gross_pct = (total_val / balance * 100) if balance > 0 else 0
            logger.info("portfolio_snapshot_loaded",
                        position_count=snapshot.position_count,
                        total_value=round(total_val, 2),
                        balance=round(balance, 2),
                        gross_exposure_pct=round(gross_pct, 2),
                        source="paper_positions_db",
                        position_ids=[p.id for p in positions])

            return snapshot
    except Exception as e:
        logger.warning("portfolio_snapshot_failed", error=str(e))
        return PortfolioSnapshot()
