"""
Bahamut Email Templates

Professional HTML templates for:
- CRITICAL alerts (red)
- WARNING alerts (amber)
- INFO alerts (blue)
- 4H Cycle Reports (full dashboard summary)
"""
from datetime import datetime, timezone


def _base_template(title: str, color: str, emoji: str, body_html: str,
                   footer: str = "") -> str:
    """Base email template with consistent branding."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""
<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#0f1419;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<div style="max-width:600px;margin:0 auto;padding:20px">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1B2A4A 0%,#0f1923 100%);border-radius:12px 12px 0 0;padding:20px 24px;border:1px solid #2d3a4f;border-bottom:none">
    <table width="100%"><tr>
      <td><span style="font-size:24px">{emoji}</span></td>
      <td style="text-align:right"><img src="https://bahamut.ai/logo.png" height="28" alt="Bahamut" style="opacity:0.8"></td>
    </tr></table>
    <h1 style="color:{color};font-size:18px;margin:12px 0 4px;font-weight:700">{title}</h1>
    <p style="color:#64748b;font-size:11px;margin:0">{now}</p>
  </div>

  <!-- Body -->
  <div style="background:#111827;padding:24px;border:1px solid #2d3a4f;border-top:none;border-radius:0 0 12px 12px">
    {body_html}
  </div>

  {footer}

  <!-- Footer -->
  <div style="text-align:center;padding:16px;color:#475569;font-size:10px">
    Bahamut.AI Trading System &bull; <a href="https://admin.bahamut.ai/v7-operations" style="color:#22d3ee;text-decoration:none">Open Dashboard</a>
  </div>

</div>
</body></html>"""


def _metric_row(label: str, value: str, color: str = "#e2e8f0") -> str:
    return f"""<tr>
      <td style="padding:6px 0;color:#94a3b8;font-size:13px">{label}</td>
      <td style="padding:6px 0;text-align:right;color:{color};font-weight:600;font-size:13px;font-family:'SF Mono',monospace">{value}</td>
    </tr>"""


def _section(title: str, content: str) -> str:
    return f"""
    <div style="margin-top:20px">
      <h3 style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin:0 0 10px;border-bottom:1px solid #1e293b;padding-bottom:6px">{title}</h3>
      {content}
    </div>"""


# ═══════════════════════════════════════════════════════
# ALERT TEMPLATES
# ═══════════════════════════════════════════════════════

def critical_template(title: str, message: str, data: dict = None) -> tuple[str, str]:
    """CRITICAL alert — red, urgent."""
    body = f"""
    <div style="background:#450a0a;border:1px solid #991b1b;border-radius:8px;padding:16px;margin-bottom:16px">
      <p style="color:#fca5a5;font-size:14px;margin:0;font-weight:600">⚠️ Immediate attention required</p>
    </div>
    <p style="color:#e2e8f0;font-size:14px;line-height:1.6;margin:0;white-space:pre-line">{message}</p>
    """
    if data:
        rows = "".join(_metric_row(k, str(v), "#f87171") for k, v in data.items())
        body += _section("Details", f'<table width="100%">{rows}</table>')

    subject = f"🚨 [CRITICAL] {title}"
    html = _base_template(title, "#f87171", "🚨", body)
    return subject, html


def warning_template(title: str, message: str, data: dict = None) -> tuple[str, str]:
    """WARNING alert — amber."""
    body = f"""
    <div style="background:#451a03;border:1px solid #92400e;border-radius:8px;padding:16px;margin-bottom:16px">
      <p style="color:#fbbf24;font-size:14px;margin:0;font-weight:600">Monitor closely</p>
    </div>
    <p style="color:#e2e8f0;font-size:14px;line-height:1.6;margin:0;white-space:pre-line">{message}</p>
    """
    if data:
        rows = "".join(_metric_row(k, str(v), "#fbbf24") for k, v in data.items())
        body += _section("Details", f'<table width="100%">{rows}</table>')

    subject = f"⚠️ [WARNING] {title}"
    html = _base_template(title, "#fbbf24", "⚠️", body)
    return subject, html


def info_template(title: str, message: str, data: dict = None) -> tuple[str, str]:
    """INFO alert — blue/cyan."""
    body = f"""
    <p style="color:#e2e8f0;font-size:14px;line-height:1.6;margin:0;white-space:pre-line">{message}</p>
    """
    if data:
        rows = "".join(_metric_row(k, str(v), "#22d3ee") for k, v in data.items())
        body += _section("Details", f'<table width="100%">{rows}</table>')

    subject = f"ℹ️ {title}"
    html = _base_template(title, "#22d3ee", "ℹ️", body)
    return subject, html


# ═══════════════════════════════════════════════════════
# 4H CYCLE REPORT
# ═══════════════════════════════════════════════════════

def cycle_report_template(cycle: dict, portfolio: dict = None,
                          conditions: dict = None) -> tuple[str, str]:
    """
    Comprehensive 4H cycle report email.
    Sent after every new-bar cycle.
    """
    status = cycle.get("status", "?")
    duration = cycle.get("duration_ms", 0)
    signals = cycle.get("signals_generated", 0)
    orders = cycle.get("orders_created", 0)
    assets = cycle.get("assets", [])
    data_source = cycle.get("data_source", "SYNTHETIC")

    status_color = "#34d399" if status == "SUCCESS" else "#f87171" if status == "ERROR" else "#fbbf24"
    status_emoji = "✅" if status == "SUCCESS" else "❌" if status == "ERROR" else "⏭️"

    # ── Status Banner ──
    body = f"""
    <div style="background:#1a2235;border:1px solid #2d3a4f;border-radius:8px;padding:16px;margin-bottom:20px">
      <table width="100%">
        <tr>
          <td style="color:#94a3b8;font-size:12px">Status</td>
          <td style="color:#94a3b8;font-size:12px">Duration</td>
          <td style="color:#94a3b8;font-size:12px">Signals</td>
          <td style="color:#94a3b8;font-size:12px">Orders</td>
          <td style="color:#94a3b8;font-size:12px">Data</td>
        </tr>
        <tr>
          <td style="color:{status_color};font-size:16px;font-weight:700;padding-top:4px">{status_emoji} {status}</td>
          <td style="color:#e2e8f0;font-size:16px;font-weight:700;font-family:monospace;padding-top:4px">{duration}ms</td>
          <td style="color:{'#22d3ee' if signals > 0 else '#e2e8f0'};font-size:16px;font-weight:700;padding-top:4px">{signals}</td>
          <td style="color:{'#34d399' if orders > 0 else '#e2e8f0'};font-size:16px;font-weight:700;padding-top:4px">{orders}</td>
          <td style="color:{'#34d399' if data_source == 'LIVE' else '#fbbf24'};font-size:12px;font-weight:600;padding-top:6px">{data_source}</td>
        </tr>
      </table>
    </div>
    """

    # ── Portfolio Summary ──
    if portfolio:
        equity = portfolio.get("equity", portfolio.get("total_equity", 100000))
        pnl = portfolio.get("pnl_total", portfolio.get("total_return_pct", 0))
        dd = portfolio.get("drawdown_pct", 0)
        risk = portfolio.get("open_risk_pct", 0)
        positions = portfolio.get("open_positions", 0)

        pnl_color = "#34d399" if pnl >= 0 else "#f87171"
        dd_color = "#f87171" if dd > 5 else "#fbbf24" if dd > 3 else "#34d399"

        rows = (
            _metric_row("Equity", f"${equity:,.0f}") +
            _metric_row("Total P&L", f"${pnl:+,.0f}", pnl_color) +
            _metric_row("Drawdown", f"{dd:.1f}%", dd_color) +
            _metric_row("Open Risk", f"{risk:.1f}%") +
            _metric_row("Open Positions", str(positions))
        )
        body += _section("Portfolio", f'<table width="100%">{rows}</table>')

    # ── Per-Asset Evaluations ──
    if assets:
        asset_html = ""
        for a in assets:
            asset_name = a.get("asset", "?")
            regime = a.get("regime", "?")
            price = a.get("bar_close", 0)
            new_bar = a.get("new_bar", False)
            summary = a.get("summary", "")

            regime_color = "#34d399" if regime == "TREND" else "#f87171" if regime == "CRASH" else "#fbbf24"
            bar_badge = '<span style="background:#164e63;color:#22d3ee;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:600">NEW BAR</span>' if new_bar else '<span style="color:#64748b;font-size:10px">same bar</span>'

            asset_html += f"""
            <div style="background:#1a2235;border:1px solid #2d3a4f;border-radius:8px;padding:14px;margin-bottom:8px">
              <div style="display:flex;align-items:center;margin-bottom:8px">
                <span style="color:#e2e8f0;font-size:15px;font-weight:700">{asset_name}</span>
                <span style="color:{regime_color};font-size:12px;font-weight:600;margin-left:12px">{regime}</span>
                <span style="color:#94a3b8;font-size:12px;font-family:monospace;margin-left:12px">${price:,.0f}</span>
                <span style="margin-left:12px">{bar_badge}</span>
              </div>
            """

            # Strategy decisions
            strats = a.get("strategies_evaluated", [])
            if strats:
                for s in strats:
                    result = s.get("result", "?")
                    reason = s.get("reason", "")
                    r_color = "#34d399" if result == "EXECUTED" else "#fbbf24" if result == "BLOCKED" else "#64748b"
                    r_emoji = "✅" if result == "EXECUTED" else "🔒" if result == "BLOCKED" else "—"
                    asset_html += f"""
                    <div style="padding:4px 0;border-top:1px solid #1e293b">
                      <span style="color:#e2e8f0;font-size:12px;font-weight:500;display:inline-block;width:110px">{s.get('strategy', '?')}</span>
                      <span style="color:{r_color};font-size:11px;font-weight:600">{r_emoji} {result}</span>
                      <span style="color:#64748b;font-size:11px;margin-left:8px">{reason}</span>
                    </div>"""
            elif summary:
                asset_html += f'<p style="color:#64748b;font-size:12px;margin:4px 0 0">{summary}</p>'

            asset_html += "</div>"

        body += _section("Asset Evaluations", asset_html)

    # ── Strategy Conditions (if available) ──
    if conditions:
        cond_html = ""
        for asset_name, cdata in conditions.items():
            for strat in cdata.get("strategies", []):
                for cond in strat.get("conditions", []):
                    passed = cond.get("passed", False)
                    icon = "✅" if passed else "❌"
                    val_color = "#34d399" if passed else "#f87171"
                    dist = f' <span style="color:#94a3b8">({cond.get("distance", "")})</span>' if cond.get("distance", "N/A") != "N/A" else ""
                    cond_html += f"""
                    <tr>
                      <td style="padding:3px 0;font-size:11px">{icon}</td>
                      <td style="padding:3px 8px;color:#94a3b8;font-size:11px">{cond['name']}</td>
                      <td style="padding:3px 0;color:{val_color};font-size:11px;font-family:monospace">{cond.get('actual', '')}{dist}</td>
                    </tr>"""

        if cond_html:
            body += _section("Strategy Conditions", f'<table width="100%">{cond_html}</table>')

    # ── Error section ──
    error = cycle.get("error", "")
    if error:
        body += f"""
        <div style="background:#450a0a;border:1px solid #991b1b;border-radius:8px;padding:16px;margin-top:20px">
          <p style="color:#fca5a5;font-size:12px;margin:0;font-weight:600">Error</p>
          <p style="color:#fca5a5;font-size:12px;margin:6px 0 0;font-family:monospace">{error}</p>
        </div>"""

    # Build subject
    asset_summary = ", ".join(f"{a.get('asset', '?')}:{a.get('regime', '?')}" for a in assets)
    if orders > 0:
        subject = f"🔔 Cycle Report: {orders} order(s) — {asset_summary}"
    elif signals > 0:
        subject = f"📊 Cycle Report: {signals} signal(s) — {asset_summary}"
    elif status == "ERROR":
        subject = f"❌ Cycle ERROR — {error[:50]}"
    else:
        subject = f"📊 4H Cycle Report — {asset_summary}"

    html = _base_template("4H Cycle Report", "#22d3ee", "📊", body)
    return subject, html
