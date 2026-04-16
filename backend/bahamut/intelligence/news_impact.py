"""
Bahamut.AI — News & Announcement Impact Intelligence

Deterministic equations for computing market impact from:
  A) Scheduled economic events (CPI, NFP, FOMC, etc.)
  B) Surprise magnitude (actual vs estimate)
  C) Breaking news headlines
  D) Source credibility
  E) Keyword severity
  F) Headline clustering (same-direction concentration)
  G) Asset-specific relevance

Output: NewsImpactAssessment — a structured, auditable impact score
that feeds into the training selector, execution gate, and consensus engine.

ALL EQUATIONS ARE DETERMINISTIC. AI is used only for enrichment, never as primary.
System works fully even if all AI APIs fail.
"""
import math
import hashlib
import structlog
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# OUTPUT SCHEMA
# ═══════════════════════════════════════════════════════════════

@dataclass
class NewsImpactAssessment:
    asset: str
    asset_class: str
    headline_count: int = 0
    event_count: int = 0
    impact_score: float = 0.0          # 0.0 to 1.0
    directional_bias: str = "NEUTRAL"  # LONG / SHORT / NEUTRAL
    shock_level: str = "NONE"          # NONE / LOW / MEDIUM / HIGH / EXTREME
    confidence: float = 0.0            # 0.0 to 1.0
    freeze_trading: bool = False
    freeze_reason: str = ""
    decay_minutes: int = 60
    catalysts: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    explanations: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — per-asset-class sensitivity weights
# ═══════════════════════════════════════════════════════════════

# How much each asset class is affected by news/events (0-1)
ASSET_CLASS_SENSITIVITY = {
    "fx": 0.85,          # FX: macro announcements very important
    "forex": 0.85,
    "indices": 0.80,     # Indices: macro + earnings + guidance
    "index": 0.80,
    "stock": 0.75,       # Stocks: company news / earnings / analyst
    "crypto": 0.70,      # Crypto: regulatory / exchange / institutional
    "commodity": 0.65,   # Commodities: macro + geopolitical + supply
}

# Component weights in the aggregate impact equation
W_EVENT = 0.30      # Scheduled event component
W_SURPRISE = 0.25   # Surprise magnitude component
W_NEWS = 0.25       # Headline component
W_CLUSTER = 0.10    # Same-direction cluster bonus
W_CONFLICT = 0.10   # Conflict penalty (subtracted)

# Trading freeze thresholds
FREEZE_THRESHOLD = 0.75          # Impact score above this => freeze
FREEZE_MINUTES_BEFORE = 15       # Minutes before high-impact event
FREEZE_MINUTES_AFTER = 10        # Minutes after high-impact event
EXTREME_SHOCK_BLOCK = True       # Hard block on EXTREME shock

# Consensus modifiers
MAX_CONSENSUS_BONUS = 15         # Max priority points bonus from aligned news
MAX_CONSENSUS_PENALTY = 20       # Max priority points penalty from opposing news


# ═══════════════════════════════════════════════════════════════
# EQUATION 1: RECENCY DECAY
# recency_weight = exp(-minutes_since_publish / half_life_minutes)
# ═══════════════════════════════════════════════════════════════

def recency_weight(published_at: str | datetime, half_life_minutes: float = 120.0) -> float:
    """Exponential decay based on age of headline/event.
    Half-life of 120 min = headline at 50% weight after 2 hours.
    """
    try:
        if isinstance(published_at, str):
            if not published_at:
                return 0.0
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        minutes_ago = max(0, (now - published_at).total_seconds() / 60)
        return math.exp(-minutes_ago / max(half_life_minutes, 1.0))
    except Exception:
        return 0.1  # Unknown time = low weight


# ═══════════════════════════════════════════════════════════════
# EQUATION 2: SOURCE CREDIBILITY
# Maps source names to credibility weights (0.0 to 1.0)
# ═══════════════════════════════════════════════════════════════

SOURCE_CREDIBILITY = {
    # Tier 1: Central banks, government agencies
    "fed": 1.0, "ecb": 1.0, "boj": 1.0, "boe": 1.0,
    "fomc": 1.0, "treasury": 0.95, "sec": 0.95,
    # Tier 2: Wire services, premier financial media
    "reuters": 0.90, "bloomberg": 0.90, "wsj": 0.85,
    "financial times": 0.85, "ft": 0.85, "cnbc": 0.80,
    "ap": 0.85, "associated press": 0.85,
    # Tier 3: Established financial media
    "marketwatch": 0.70, "barron's": 0.70, "barrons": 0.70,
    "seeking alpha": 0.60, "investopedia": 0.55,
    "coindesk": 0.65, "cointelegraph": 0.60, "the block": 0.65,
    # Tier 4: General media
    "cnn": 0.60, "bbc": 0.65, "nyt": 0.65, "new york times": 0.65,
    # Tier 5: Crypto-specific
    "decrypt": 0.55, "crypto news": 0.50,
    # Fallback
    "finnhub": 0.60, "forexfactory": 0.70,
}


def source_credibility(source_name: str) -> float:
    """Map a source name to credibility weight."""
    if not source_name:
        return 0.3
    s = source_name.lower().strip()
    # Check exact match first, then partial
    if s in SOURCE_CREDIBILITY:
        return SOURCE_CREDIBILITY[s]
    for key, weight in SOURCE_CREDIBILITY.items():
        if key in s or s in key:
            return weight
    return 0.4  # Unknown source = low-mid credibility


# ═══════════════════════════════════════════════════════════════
# EQUATION 3: HEADLINE SEVERITY (keyword-based)
# Score each headline by keyword dictionaries
# ═══════════════════════════════════════════════════════════════

BULLISH_KEYWORDS = {
    # Strong bullish
    "beat": 0.7, "beats": 0.7, "surpass": 0.7, "exceed": 0.6,
    "approval": 0.6, "approved": 0.6, "easing": 0.7, "dovish": 0.8,
    "growth": 0.5, "upgrade": 0.7, "upgraded": 0.7, "inflow": 0.6,
    "rally": 0.5, "surge": 0.6, "breakout": 0.5, "record high": 0.7,
    "all-time high": 0.8, "ath": 0.7, "stimulus": 0.6,
    "rate cut": 0.8, "rate cuts": 0.8, "cutting rates": 0.8,
    "etf approved": 0.9, "etf approval": 0.9,
    "institutional buy": 0.7, "accumulation": 0.5,
    # Moderate bullish
    "positive": 0.4, "optimistic": 0.4, "bullish": 0.5,
    "recovery": 0.4, "rebound": 0.5, "higher": 0.3,
}

BEARISH_KEYWORDS = {
    # Strong bearish
    "miss": 0.7, "misses": 0.7, "war": 0.8, "tariff": 0.7, "tariffs": 0.7,
    "ban": 0.8, "banned": 0.8, "downgrade": 0.7, "downgraded": 0.7,
    "default": 0.9, "inflation shock": 0.8, "hawkish": 0.7,
    "recession": 0.8, "layoffs": 0.5, "bankruptcy": 0.9,
    "rate hike": 0.7, "rate hikes": 0.7, "raising rates": 0.7,
    "crash": 0.7, "plunge": 0.6, "dump": 0.5, "collapse": 0.8,
    "hack": 0.7, "hacked": 0.8, "exploit": 0.7, "rug pull": 0.9,
    "delisted": 0.7, "delist": 0.7, "sec charges": 0.8,
    "sanctions": 0.7, "embargo": 0.6,
    # Moderate bearish
    "negative": 0.4, "pessimistic": 0.4, "bearish": 0.5,
    "decline": 0.4, "lower": 0.3, "sell-off": 0.6, "selloff": 0.6,
    "outflow": 0.5, "liquidation": 0.7, "liquidated": 0.7,
}

SHOCK_KEYWORDS = {
    # Extreme shock events
    "emergency": 0.9, "surprise": 0.6, "halt": 0.8, "halted": 0.8,
    "sanctions": 0.7, "attack": 0.8, "invasion": 0.9,
    "liquidation": 0.7, "bankruptcy": 0.9, "insolvency": 0.9,
    "circuit breaker": 0.9, "flash crash": 0.9,
    "black swan": 1.0, "force majeure": 0.9,
    "terrorist": 0.9, "assassination": 0.9,
    "nuclear": 0.9, "pandemic": 0.8,
}


def headline_severity(title: str) -> dict:
    """Score a headline by keyword matching.
    Returns: {bullish_score, bearish_score, shock_score, net_direction, severity}
    """
    if not title:
        return {"bullish": 0, "bearish": 0, "shock": 0, "direction": "NEUTRAL", "severity": 0}

    text = title.lower()
    bull = max((v for k, v in BULLISH_KEYWORDS.items() if k in text), default=0)
    bear = max((v for k, v in BEARISH_KEYWORDS.items() if k in text), default=0)
    shock = max((v for k, v in SHOCK_KEYWORDS.items() if k in text), default=0)

    if bull > bear + 0.1:
        direction = "LONG"
    elif bear > bull + 0.1:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    severity = max(bull, bear, shock)

    return {
        "bullish": round(bull, 2),
        "bearish": round(bear, 2),
        "shock": round(shock, 2),
        "direction": direction,
        "severity": round(severity, 2),
    }


# ═══════════════════════════════════════════════════════════════
# EQUATION 4: EVENT SURPRISE SCORE
# surprise_z = abs(actual - estimate) / max(abs(estimate), epsilon)
# Signed surprise preserves bullish/bearish meaning
# ═══════════════════════════════════════════════════════════════

# Events where higher actual = bullish
HIGHER_IS_BETTER = {
    "gdp", "growth", "employment", "payroll", "nfp", "non-farm",
    "retail sales", "consumer confidence", "pmi", "ism",
    "housing starts", "building permits", "earnings",
}

# Events where lower actual = bullish
LOWER_IS_BETTER = {
    "unemployment", "jobless", "cpi", "inflation", "pce",
    "interest rate", "rate decision",  # Higher rates = tighter = bearish
}


def event_surprise_score(event: dict) -> dict:
    """Compute surprise z-score from actual vs estimate.
    Returns: {surprise_z, signed_surprise, direction, magnitude}
    """
    actual = event.get("actual")
    estimate = event.get("estimate")
    prev = event.get("prev")
    name = (event.get("event") or event.get("name") or "").lower()

    if actual is None or estimate is None:
        # No surprise data — check if event is upcoming
        return {"surprise_z": 0, "signed_surprise": 0, "direction": "NEUTRAL", "magnitude": 0}

    try:
        actual_f = float(actual)
        estimate_f = float(estimate)
    except (ValueError, TypeError):
        return {"surprise_z": 0, "signed_surprise": 0, "direction": "NEUTRAL", "magnitude": 0}

    epsilon = max(abs(estimate_f) * 0.01, 0.001)
    raw_surprise = actual_f - estimate_f
    surprise_z = abs(raw_surprise) / max(abs(estimate_f), epsilon)
    surprise_z = min(surprise_z, 5.0)  # Cap at 5 sigma

    # Determine direction based on event type
    # Check LOWER_IS_BETTER first — "unemployment" must not match "employment"
    lower_good = any(k in name for k in LOWER_IS_BETTER)
    higher_good = any(k in name for k in HIGHER_IS_BETTER) if not lower_good else False

    if higher_good:
        direction = "LONG" if raw_surprise > 0 else "SHORT"
    elif lower_good:
        direction = "SHORT" if raw_surprise > 0 else "LONG"  # Higher inflation = bearish
    else:
        direction = "LONG" if raw_surprise > 0 else "SHORT"  # Default: higher = better

    signed = surprise_z if direction == "LONG" else -surprise_z

    # Magnitude classification
    if surprise_z >= 2.0:
        magnitude = "EXTREME"
    elif surprise_z >= 1.0:
        magnitude = "HIGH"
    elif surprise_z >= 0.5:
        magnitude = "MEDIUM"
    elif surprise_z >= 0.2:
        magnitude = "LOW"
    else:
        magnitude = "NONE"

    return {
        "surprise_z": round(surprise_z, 3),
        "signed_surprise": round(signed, 3),
        "direction": direction,
        "magnitude": magnitude,
    }


# ═══════════════════════════════════════════════════════════════
# EQUATION 5: SCHEDULED EVENT COMPONENT
# Impact based on event proximity, impact level, and surprise
# ═══════════════════════════════════════════════════════════════

EVENT_IMPACT_WEIGHTS = {
    "high": 1.0,
    "medium": 0.5,
    "low": 0.2,
}


def scheduled_event_component(events: list[dict], asset: str, asset_class: str) -> dict:
    """Score the scheduled event impact for an asset.
    Returns: {score, direction, freeze, freeze_reason, nearest_event, explanations}
    """
    if not events:
        return {"score": 0, "direction": "NEUTRAL", "freeze": False,
                "freeze_reason": "", "nearest_event": None, "explanations": []}

    now = datetime.now(timezone.utc)
    score = 0.0
    directions = []
    freeze = False
    freeze_reason = ""
    nearest = None
    nearest_minutes = float("inf")
    explanations = []

    for ev in events:
        impact = ev.get("impact", "low")
        impact_w = EVENT_IMPACT_WEIGHTS.get(impact, 0.2)

        # Parse event time
        try:
            ev_time_str = ev.get("time") or ev.get("date", "")
            if "T" in ev_time_str:
                ev_time = datetime.fromisoformat(ev_time_str.replace("Z", "+00:00"))
            else:
                ev_time = datetime.strptime(ev_time_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            continue

        minutes_away = (ev_time - now).total_seconds() / 60

        # Track nearest event
        if abs(minutes_away) < abs(nearest_minutes):
            nearest_minutes = minutes_away
            nearest = ev

        # Recency/proximity weight
        if minutes_away > 0:
            # Upcoming event — weight increases as it approaches
            proximity = math.exp(-minutes_away / 60)  # Half-life 60 min
        else:
            # Past event — decay after release
            proximity = math.exp(minutes_away / 30)  # Faster decay (30 min half-life)

        # Surprise component (if actual is available)
        surprise = event_surprise_score(ev)
        surprise_contrib = abs(surprise["signed_surprise"]) * 0.3

        ev_score = impact_w * proximity + surprise_contrib
        score += ev_score

        if surprise["direction"] != "NEUTRAL":
            directions.append(surprise["direction"])
            explanations.append(
                f"{ev.get('event', 'Event')}: surprise {surprise['magnitude']} "
                f"({surprise['direction']}, z={surprise['surprise_z']:.2f})"
            )

        # Freeze logic: high-impact event within window
        if impact == "high":
            if 0 < minutes_away <= FREEZE_MINUTES_BEFORE:
                freeze = True
                freeze_reason = f"High-impact event '{ev.get('event', '')}' in {int(minutes_away)}min"
                explanations.append(f"FREEZE: {freeze_reason}")
            elif -FREEZE_MINUTES_AFTER <= minutes_away <= 0:
                freeze = True
                freeze_reason = f"High-impact event '{ev.get('event', '')}' released {int(-minutes_away)}min ago"
                explanations.append(f"FREEZE: {freeze_reason}")

    # Aggregate direction
    long_count = sum(1 for d in directions if d == "LONG")
    short_count = sum(1 for d in directions if d == "SHORT")
    if long_count > short_count + 1:
        direction = "LONG"
    elif short_count > long_count + 1:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    return {
        "score": round(min(score, 1.0), 3),
        "direction": direction,
        "freeze": freeze,
        "freeze_reason": freeze_reason,
        "nearest_event": nearest,
        "explanations": explanations,
    }


# ═══════════════════════════════════════════════════════════════
# EQUATION 6: HEADLINE COMPONENT
# Aggregate headline scores with recency + credibility weighting
# ═══════════════════════════════════════════════════════════════

def headline_component(headlines: list[dict]) -> dict:
    """Score the aggregate headline impact.
    Returns: {score, direction, cluster_bonus, conflict_penalty, explanations}
    """
    if not headlines:
        return {"score": 0, "direction": "NEUTRAL", "cluster_bonus": 0,
                "conflict_penalty": 0, "explanations": []}

    weighted_bull = 0.0
    weighted_bear = 0.0
    weighted_shock = 0.0
    total_weight = 0.0
    directions = []
    explanations = []

    for h in headlines:
        title = h.get("title", "")
        source = h.get("source", "")
        published = h.get("published", "")

        sev = headline_severity(title)
        rec = recency_weight(published)
        cred = source_credibility(source)
        w = rec * cred

        weighted_bull += sev["bullish"] * w
        weighted_bear += sev["bearish"] * w
        weighted_shock += sev["shock"] * w
        total_weight += w

        if sev["severity"] > 0.3:
            directions.append(sev["direction"])
            if sev["severity"] > 0.5:
                explanations.append(f"'{title[:60]}' [{source}] → {sev['direction']} ({sev['severity']:.1f})")

    if total_weight == 0:
        return {"score": 0, "direction": "NEUTRAL", "cluster_bonus": 0,
                "conflict_penalty": 0, "explanations": explanations}

    # Normalize
    norm_bull = weighted_bull / total_weight
    norm_bear = weighted_bear / total_weight
    norm_shock = weighted_shock / total_weight

    # Freshness dampening: if all headlines are stale (low total_weight),
    # the normalized scores are misleading — dampen the final score.
    # A single fresh credible headline has weight ~0.9. Baseline = 0.5.
    freshness_factor = min(1.0, total_weight / 0.5)
    norm_bull *= freshness_factor
    norm_bear *= freshness_factor
    norm_shock *= freshness_factor

    # Cluster bonus: same-direction headlines reinforce each other
    long_count = sum(1 for d in directions if d == "LONG")
    short_count = sum(1 for d in directions if d == "SHORT")
    total_directional = long_count + short_count

    cluster_bonus = 0.0
    if total_directional >= 3:
        dominant = max(long_count, short_count)
        cluster_ratio = dominant / total_directional
        if cluster_ratio >= 0.75:
            cluster_bonus = 0.2 * cluster_ratio
            explanations.append(f"Headline cluster: {dominant}/{total_directional} same direction (+{cluster_bonus:.2f})")

    # Conflict penalty: contradictory headlines reduce confidence
    conflict_penalty = 0.0
    if total_directional >= 2:
        minority = min(long_count, short_count)
        if minority > 0:
            conflict_ratio = minority / total_directional
            if conflict_ratio >= 0.3:
                conflict_penalty = 0.15 * conflict_ratio
                explanations.append(f"Conflicting headlines: {minority} opposing ({-conflict_penalty:.2f})")

    score = max(norm_bull, norm_bear, norm_shock) + cluster_bonus
    score = min(score, 1.0)

    if norm_bull > norm_bear + 0.05:
        direction = "LONG"
    elif norm_bear > norm_bull + 0.05:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    return {
        "score": round(score, 3),
        "direction": direction,
        "cluster_bonus": round(cluster_bonus, 3),
        "conflict_penalty": round(conflict_penalty, 3),
        "explanations": explanations,
    }


# ═══════════════════════════════════════════════════════════════
# EQUATION 7: AGGREGATE IMPACT
# impact_score = clamp(
#   w_event * event_component +
#   w_surprise * surprise_component +
#   w_news * headline_component +
#   w_cluster * cluster_bonus -
#   w_conflict * conflict_penalty
# , 0, 1)
# ═══════════════════════════════════════════════════════════════

# Phase 4 Item 10: origin classification keywords by class.
# Used to tag headlines as asset-specific vs class-level vs macro.
_CLASS_KEYWORDS = {
    "crypto": {
        "bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency",
        "altcoin", "stablecoin", "defi", "nft", "sec crypto", "etf",
        "binance", "coinbase", "kraken", "ftx", "tether", "usdt",
    },
    "stock": {
        "s&p", "s&p 500", "spx", "nasdaq", "dow", "dow jones", "ndx",
        "nyse", "equities", "equity markets", "wall street", "stocks",
        "sector", "earnings season", "q1", "q2", "q3", "q4",
    },
    "forex": {
        "fx", "forex", "dollar", "usd", "eur", "euro", "yen", "gbp",
        "currency", "central bank", "dxy",
    },
}
_MACRO_KEYWORDS = {
    "fed", "federal reserve", "fomc", "powell", "yellen", "treasury",
    "inflation", "cpi", "pce", "nfp", "unemployment", "recession",
    "gdp", "rate hike", "rate cut", "interest rate", "monetary policy",
    "ecb", "boj", "pboc", "geopolitical", "war", "sanction",
}


def _classify_news_origins(
    asset: str,
    asset_class: str,
    headlines: list[dict],
    events: list[dict],
) -> dict:
    """Split news impact into asset-specific / class-level / macro sources.

    Classification rules (per headline):
      1. If the asset ticker or its canonical name appears in the title →
         asset-specific (highest priority; could also be class or macro).
      2. Else if any class-keyword appears → class-level.
      3. Else if any macro-keyword appears → macro.
      4. Else → unclassified (still counted in totals but not attributed).

    Scheduled events are always macro (FOMC, CPI, etc. affect all classes).

    Returns:
      {asset_specific_score, class_level_score, macro_score,
       unclassified_score, total_headlines_by_origin (dict),
       top_sources (list of {source, weight, origin})}
    """
    asset_tokens = {asset.lower(), asset.lower().replace("usd", "")}
    # Add the crypto full names
    CRYPTO_NAMES = {
        "btcusd": "bitcoin", "ethusd": "ethereum", "solusd": "solana",
        "xrpusd": "ripple", "adausd": "cardano", "dogeusd": "dogecoin",
        "avaxusd": "avalanche", "linkusd": "chainlink", "maticusd": "polygon",
        "dotusd": "polkadot", "atomusd": "cosmos", "uniusd": "uniswap",
        "ltcusd": "litecoin", "bnbusd": "binance coin",
    }
    if asset.lower() in CRYPTO_NAMES:
        asset_tokens.add(CRYPTO_NAMES[asset.lower()])

    class_keywords = _CLASS_KEYWORDS.get(asset_class, set())

    asset_weight = class_weight = macro_weight = unc_weight = 0.0
    counts = {"asset": 0, "class": 0, "macro": 0, "unclassified": 0}
    source_tags: list[dict] = []

    for h in headlines:
        title_lower = (h.get("title", "") or "").lower()
        source = h.get("source", "") or ""
        published = h.get("published", "") or ""
        try:
            rec = recency_weight(published)
            cred = source_credibility(source)
            w = rec * cred
        except Exception:
            w = 0.5

        # Classify
        if any(tok and tok in title_lower for tok in asset_tokens):
            origin = "asset"
            asset_weight += w
        elif any(kw in title_lower for kw in class_keywords):
            origin = "class"
            class_weight += w
        elif any(kw in title_lower for kw in _MACRO_KEYWORDS):
            origin = "macro"
            macro_weight += w
        else:
            origin = "unclassified"
            unc_weight += w
        counts[origin] += 1
        source_tags.append({
            "source": source, "title": (h.get("title") or "")[:80],
            "origin": origin, "weight": round(w, 3),
            "published": published,
        })

    # Events: weighted as macro (scheduled events are macro by nature)
    event_macro_boost = 0.0
    for ev in events:
        try:
            event_macro_boost += float(ev.get("importance", 1))
        except Exception:
            event_macro_boost += 1
    # Normalize event boost to headline-equivalent weight
    macro_weight += event_macro_boost * 0.5

    total_weight = max(
        asset_weight + class_weight + macro_weight + unc_weight, 1e-9
    )
    # Sort sources by weight desc
    source_tags.sort(key=lambda s: s["weight"], reverse=True)

    return {
        "asset_specific_score": round(asset_weight / total_weight, 3),
        "class_level_score": round(class_weight / total_weight, 3),
        "macro_score": round(macro_weight / total_weight, 3),
        "unclassified_score": round(unc_weight / total_weight, 3),
        "counts_by_origin": counts,
        "event_macro_boost": round(event_macro_boost, 2),
        "top_sources": source_tags,
    }


def compute_news_impact(
    asset: str,
    asset_class: str,
    headlines: list[dict] | None = None,
    events: list[dict] | None = None,
) -> NewsImpactAssessment:
    """Main entry point: compute full news impact assessment for an asset.

    This is deterministic — no AI calls. Works even if all external APIs fail.
    """
    headlines = headlines or []
    events = events or []

    assessment = NewsImpactAssessment(
        asset=asset,
        asset_class=asset_class,
        headline_count=len(headlines),
        event_count=len(events),
    )

    # Asset class sensitivity multiplier
    sensitivity = ASSET_CLASS_SENSITIVITY.get(asset_class, 0.5)

    # Component 1: Scheduled events
    ev_result = scheduled_event_component(events, asset, asset_class)

    # Component 2: Headlines
    hl_result = headline_component(headlines)

    # Component 3: Find strongest surprise from events
    best_surprise = {"surprise_z": 0, "direction": "NEUTRAL", "magnitude": "NONE"}
    for ev in events:
        s = event_surprise_score(ev)
        if s["surprise_z"] > best_surprise["surprise_z"]:
            best_surprise = s

    # Aggregate impact equation
    raw_impact = (
        W_EVENT * ev_result["score"]
        + W_SURPRISE * min(best_surprise["surprise_z"] / 2.0, 1.0)  # Normalize z to 0-1
        + W_NEWS * hl_result["score"]
        + W_CLUSTER * hl_result["cluster_bonus"]
        - W_CONFLICT * hl_result["conflict_penalty"]
    )

    # Apply asset-class sensitivity
    impact_score = max(0.0, min(1.0, raw_impact * sensitivity))
    assessment.impact_score = round(impact_score, 3)

    # Direction: combine event and headline direction
    dirs = []
    if ev_result["direction"] != "NEUTRAL":
        dirs.extend([ev_result["direction"]] * 2)  # Events weighted 2x
    if hl_result["direction"] != "NEUTRAL":
        dirs.append(hl_result["direction"])
    if best_surprise["direction"] != "NEUTRAL":
        dirs.append(best_surprise["direction"])

    long_votes = sum(1 for d in dirs if d == "LONG")
    short_votes = sum(1 for d in dirs if d == "SHORT")
    if long_votes > short_votes:
        assessment.directional_bias = "LONG"
    elif short_votes > long_votes:
        assessment.directional_bias = "SHORT"
    else:
        assessment.directional_bias = "NEUTRAL"

    # Shock level
    if impact_score >= 0.85 or best_surprise["magnitude"] == "EXTREME":
        assessment.shock_level = "EXTREME"
    elif impact_score >= 0.65 or best_surprise["magnitude"] == "HIGH":
        assessment.shock_level = "HIGH"
    elif impact_score >= 0.40:
        assessment.shock_level = "MEDIUM"
    elif impact_score >= 0.15:
        assessment.shock_level = "LOW"
    else:
        assessment.shock_level = "NONE"

    # Confidence: higher when direction is clear, lower when conflicting
    if hl_result["conflict_penalty"] > 0.1:
        assessment.confidence = max(0.2, impact_score - hl_result["conflict_penalty"])
    else:
        assessment.confidence = round(min(1.0, impact_score * 1.2), 3)

    # Trading freeze
    if ev_result["freeze"]:
        assessment.freeze_trading = True
        assessment.freeze_reason = ev_result["freeze_reason"]
    elif impact_score >= FREEZE_THRESHOLD:
        assessment.freeze_trading = True
        assessment.freeze_reason = f"Impact score {impact_score:.2f} exceeds threshold {FREEZE_THRESHOLD}"
    elif assessment.shock_level == "EXTREME" and EXTREME_SHOCK_BLOCK:
        assessment.freeze_trading = True
        assessment.freeze_reason = f"EXTREME shock detected"

    # Decay time
    if assessment.shock_level in ("HIGH", "EXTREME"):
        assessment.decay_minutes = 120
    elif assessment.shock_level == "MEDIUM":
        assessment.decay_minutes = 60
    else:
        assessment.decay_minutes = 30

    # Collect explanations, catalysts, risks
    assessment.explanations = ev_result["explanations"] + hl_result["explanations"]
    if assessment.directional_bias == "LONG":
        assessment.catalysts = [e for e in assessment.explanations if "LONG" in e or "bullish" in e.lower()]
    elif assessment.directional_bias == "SHORT":
        assessment.risks = [e for e in assessment.explanations if "SHORT" in e or "bearish" in e.lower()]

    # Meta for debugging
    assessment.meta = {
        "event_score": ev_result["score"],
        "headline_score": hl_result["score"],
        "surprise_z": best_surprise["surprise_z"],
        "surprise_magnitude": best_surprise["magnitude"],
        "cluster_bonus": hl_result["cluster_bonus"],
        "conflict_penalty": hl_result["conflict_penalty"],
        "sensitivity": sensitivity,
        "raw_impact": round(raw_impact, 3),
    }

    # ── Phase 4 Item 10: origin classification ──
    # Split the impact into asset-specific, class-wide, and macro components
    # so downstream gate decisions can distinguish "asset breaking news"
    # from "market-wide macro caution" from "class-level risk".
    try:
        origins = _classify_news_origins(asset, asset_class, headlines, events)
        assessment.meta["origins"] = origins
        # Populate top-level shortcut fields on the assessment
        # (these then get copied to AssetNewsState).
        assessment.meta["asset_specific_impact"] = origins["asset_specific_score"]
        assessment.meta["class_risk_impact"] = origins["class_level_score"]
        assessment.meta["macro_risk_impact"] = origins["macro_score"]
        # Source list for auditing — first 5 by weight
        assessment.meta["top_sources"] = origins["top_sources"][:5]
    except Exception as _orig_err:
        assessment.meta["origins_error"] = str(_orig_err)[:120]

    return assessment


# ═══════════════════════════════════════════════════════════════
# EQUATION 8: CONSENSUS MODIFIER
# Adjusts priority score based on news alignment with trade direction
# ═══════════════════════════════════════════════════════════════

def compute_consensus_modifier(
    assessment: NewsImpactAssessment,
    trade_direction: str,
) -> dict:
    """Compute how news should modify a trade signal's priority.

    Returns:
      modifier: int — points to add (positive) or subtract (negative) from priority
      explanation: str — human-readable reason
      action: str — "boost", "penalize", "freeze", "neutral"
    """
    if assessment.impact_score < 0.1:
        return {"modifier": 0, "explanation": "No significant news impact", "action": "neutral"}

    # Freeze check
    if assessment.freeze_trading:
        return {
            "modifier": -MAX_CONSENSUS_PENALTY,
            "explanation": f"FROZEN: {assessment.freeze_reason}",
            "action": "freeze",
        }

    # Direction alignment check
    aligned = (
        (assessment.directional_bias == "LONG" and trade_direction == "LONG")
        or (assessment.directional_bias == "SHORT" and trade_direction == "SHORT")
    )
    opposed = (
        (assessment.directional_bias == "LONG" and trade_direction == "SHORT")
        or (assessment.directional_bias == "SHORT" and trade_direction == "LONG")
    )

    if aligned:
        bonus = min(MAX_CONSENSUS_BONUS, int(assessment.impact_score * MAX_CONSENSUS_BONUS * assessment.confidence))
        return {
            "modifier": bonus,
            "explanation": f"News aligned with {trade_direction} (impact={assessment.impact_score:.2f}, "
                           f"bias={assessment.directional_bias}, +{bonus}pts)",
            "action": "boost",
        }
    elif opposed:
        penalty = min(MAX_CONSENSUS_PENALTY, int(assessment.impact_score * MAX_CONSENSUS_PENALTY * assessment.confidence))
        return {
            "modifier": -penalty,
            "explanation": f"News OPPOSES {trade_direction} (impact={assessment.impact_score:.2f}, "
                           f"bias={assessment.directional_bias}, -{penalty}pts)",
            "action": "penalize",
        }
    else:
        return {"modifier": 0, "explanation": "News neutral for this direction", "action": "neutral"}


# ═══════════════════════════════════════════════════════════════
# HEADLINE DEDUP
# ═══════════════════════════════════════════════════════════════

def dedupe_headlines(headlines: list[dict]) -> list[dict]:
    """Remove duplicate headlines across sources using title hash."""
    seen = set()
    unique = []
    for h in headlines:
        title = (h.get("title") or "").strip().lower()
        if not title:
            continue
        # Hash first 80 chars to catch near-duplicates
        key = hashlib.md5(title[:80].encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique


# ═══════════════════════════════════════════════════════════════
# ASYNC HELPER: Fetch news + events for an asset
# ═══════════════════════════════════════════════════════════════

async def fetch_and_assess(asset: str, asset_class: str) -> NewsImpactAssessment:
    """Async helper: fetch headlines + events, then compute impact.
    Falls back gracefully if APIs fail.
    """
    headlines = []
    events = []

    try:
        from bahamut.ingestion.adapters.news import news_adapter, econ_calendar
        headlines = await news_adapter.get_asset_news(asset, count=10)
        events = await econ_calendar.get_upcoming_events(days_ahead=1)
    except Exception as e:
        logger.warning("news_impact_fetch_failed", asset=asset, error=str(e)[:100])

    headlines = dedupe_headlines(headlines)
    return compute_news_impact(asset, asset_class, headlines, events)


# ═══════════════════════════════════════════════════════════════
# SYNC HELPER: For training orchestrator (sync context)
# ═══════════════════════════════════════════════════════════════

def compute_news_impact_sync(asset: str, asset_class: str) -> NewsImpactAssessment:
    """Synchronous version — uses cached data if available, otherwise returns empty assessment.
    The training orchestrator runs in sync context and can't await.
    """
    import os
    try:
        import redis as _redis
        import json
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))

        # Try cached headlines
        raw_hl = r.get(f"bahamut:news:headlines:{asset}")
        headlines = json.loads(raw_hl) if raw_hl else []

        # Try cached events
        raw_ev = r.get("bahamut:news:events")
        events = json.loads(raw_ev) if raw_ev else []

        if headlines or events:
            headlines = dedupe_headlines(headlines)
            return compute_news_impact(asset, asset_class, headlines, events)
    except Exception:
        pass

    # No cached data available — return empty assessment
    return NewsImpactAssessment(asset=asset, asset_class=asset_class)


def cache_news_data(asset: str, headlines: list[dict], events: list[dict] | None = None):
    """Cache fetched news data in Redis for sync access by training orchestrator."""
    import os
    try:
        import redis as _redis
        import json
        r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        if headlines:
            r.setex(f"bahamut:news:headlines:{asset}", 900, json.dumps(headlines))  # 15 min TTL
        if events:
            r.setex("bahamut:news:events", 900, json.dumps(events))
    except Exception:
        pass
