"""Primitive HTML components for county diagnostic dashboards.

All functions are pure: they take data and return HTML strings.
Nothing here is county- or scenario-specific — it is a reusable
building-block library for assembling dashboard pages.
"""
from __future__ import annotations

from typing import List, Optional


# ---------------------------------------------------------------------------
# CSS — plain string, no Python f-string brace-escaping needed
# ---------------------------------------------------------------------------

CSS = """
    body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #f7f7f7; }
    .header { background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 18px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 16px; }
    .card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 12px; }
    .metric-card { background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 20px; text-align: center; }
    .section { background: #fff7e6; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.08); padding: 12px; grid-column: 1 / -1; }
    .section summary { cursor: pointer; font-size: 18px; font-weight: 600; color: #b00020; }
    .section-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-top: 12px; }
    @media (max-width: 1100px) { .section-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 720px) { .section-grid { grid-template-columns: repeat(1, minmax(0, 1fr)); } }
    h1 { margin: 0 0 6px; }
    h2 { margin: 6px 0 12px; font-size: 18px; }
    .imgwrap img { width: 100%; height: auto; border-radius: 6px; cursor: zoom-in; }
    .muted { color: #666; font-size: 12px; }
    .metric-value { font-size: 24px; font-weight: bold; color: #2c5aa0; line-height: 1.2; }
    .metric-value small { font-size: 12px; color: #666; font-weight: normal; display: block; margin-top: 4px; }
    .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; align-items: stretch; }
    .metrics-grid-compact { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .metrics-grid-compact .metric-block { padding: 12px; }
    .metrics-grid-compact .metric-value { font-size: 20px; }
    .metric-block { background: #fbfbfb; border: 1px solid #eee; border-radius: 8px; padding: 16px; text-align: center; }
    .kmtbl { width: 100%; border-collapse: collapse; }
    .kmtbl th, .kmtbl td { padding: 10px 12px; border-bottom: 1px solid #eee; }
    .kmtbl th { text-align: center; font-weight: 600; color: #2c3e50; }
    .kmtbl td { text-align: center; }
    .kmtbl td:first-child { text-align: left; color: #666; width: 40%; }
    .kmtbl td.val { text-align: right; }
    .kmtbl td.money { text-align: right; }
    .val { font-weight: 700; color: #2c5aa0; }
    .formula { color: #888; font-size: 11px; margin-top: 2px; }
    .money { color: #1a5; font-weight: 700; }
    .highlight-min { background: #eaffea; }
    .method { margin-bottom: 8px; }
    .method summary { cursor: pointer; font-weight: 600; color: #2c3e50; }
    .method-body { margin-top: 6px; }
    .method-section { margin: 6px 0 10px; }
    .method-label { font-size: 12px; font-weight: 600; color: #555; margin-bottom: 4px; }
    .method-table { width: 100%; border-collapse: collapse; font-size: 12px; }
    .method-table td { border-bottom: 1px solid #eee; padding: 4px 6px; vertical-align: top; }
    .method-key { width: 30%; color: #444; }
    .mono { font-family: "Courier New", monospace; font-size: 12px; background: #f5f5f5; padding: 4px 6px; border-radius: 4px; display: inline-block; }
    .code-list { margin: 4px 0 8px 18px; }
"""


# ---------------------------------------------------------------------------
# Formatters — one canonical definition, importable from anywhere
# ---------------------------------------------------------------------------

def fmt_money(v: Optional[float]) -> str:
    """Format as '$X,XXX' or 'N/A'."""
    try:
        return f"${float(v):,.0f}" if v is not None else "N/A"
    except Exception:
        return "N/A"


def fmt_kwh(v: Optional[float]) -> str:
    """Format as 'X,XXX' (no unit suffix) or 'N/A'."""
    try:
        return f"{float(v):,.0f}" if v is not None else "N/A"
    except Exception:
        return "N/A"


def fmt_kw(v: Optional[float]) -> str:
    """Format as 'X.X' or 'N/A'."""
    try:
        return f"{float(v):,.1f}" if v is not None else "N/A"
    except Exception:
        return "N/A"


# ---------------------------------------------------------------------------
# Primitive components — all pure functions returning HTML strings
# ---------------------------------------------------------------------------

def img_card(
    title: str,
    b64: Optional[str],
    *,
    alt: str = "",
    fallback: str = "No data available",
    note: Optional[str] = None,
) -> str:
    """A card containing a full-width clickable image, or a muted fallback."""
    parts = [f'<div class="card"><h2>{title}</h2>']
    if b64:
        parts.append(
            f'<div class="imgwrap">'
            f'<a href="data:image/png;base64,{b64}" target="_blank" rel="noopener noreferrer">'
            f'<img src="data:image/png;base64,{b64}" alt="{alt}"/>'
            f'</a></div>'
        )
        if note:
            parts.append(f'<div class="muted">{note}</div>')
    else:
        parts.append(f'<div class="muted">{fallback}</div>')
    parts.append("</div>")
    return "\n".join(parts)


def html_card(title: str, body_html: str) -> str:
    """A card with an arbitrary HTML body."""
    return f'<div class="card"><h2>{title}</h2>{body_html}</div>'


def section(title: str, cards: List[str], *, collapsible: bool = True) -> str:
    """A full-width collapsible (or static) section wrapping a responsive card grid."""
    inner = "\n".join(cards)
    if collapsible:
        return (
            f'<details class="section">'
            f'<summary>{title}</summary>'
            f'<div class="section-grid">{inner}</div>'
            f'</details>'
        )
    return (
        f'<div class="section">'
        f'<div style="font-size:18px;font-weight:600;color:#b00020;margin-bottom:12px;">{title}</div>'
        f'<div class="section-grid">{inner}</div>'
        f'</div>'
    )


def page_shell(
    title: str,
    county_title: str,
    scen_title: str,
    housing_type: str,
    body: str,
) -> str:
    """Wrap body content in a complete HTML document with shared CSS and a page header."""
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="header">
    <h1>County Diagnostics</h1>
    <div class="muted">{county_title} — {scen_title} — {housing_type}</div>
  </div>
  {body}
</body>
</html>"""
