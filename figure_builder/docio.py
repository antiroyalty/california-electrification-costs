"""Pure primitives for embedding figures and patching HTML documents.

Every function here is a pure function of its arguments (string/figure in,
string out) with no file or global state, so the fiddly parts of the old
generators (base64 embedding, idempotent marker replacement, section splitting)
become unit-testable instead of regex soup buried in one-off scripts.

Markers are HTML comments of the form `<!-- NAME-START -->` / `<!-- NAME-END -->`.
"""
from __future__ import annotations

import base64
import io
import re
from typing import List, Tuple


# --- figure embedding -------------------------------------------------------
def embed_png(fig, close: bool = True) -> str:
    """PNG-encode a matplotlib figure to a base64 string (no data-URI prefix)."""
    import matplotlib.pyplot as plt

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    if close:
        plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def figure_html(b64: str, caption: str, alt: str) -> str:
    """A `<figure>` block wrapping a base64 PNG, matching the claims-doc style."""
    return (
        f'<figure class="fig"><img src="data:image/png;base64,{b64}" alt="{alt}" />'
        f'<figcaption>{caption}</figcaption></figure>'
    )


# --- markers ----------------------------------------------------------------
def start_marker(name: str) -> str:
    return f"<!-- {name}-START -->"


def end_marker(name: str) -> str:
    return f"<!-- {name}-END -->"


def wrap_markers(name: str, inner: str) -> str:
    """Wrap `inner` in START/END comment markers named `name`."""
    return f"{start_marker(name)}\n{inner}\n{end_marker(name)}"


def has_markers(html: str, name: str) -> bool:
    return start_marker(name) in html and end_marker(name) in html


def strip_between_markers(html: str, name: str) -> str:
    """Remove a marked block (markers included) if present. Idempotent."""
    pat = re.compile(
        r"\n?\s*" + re.escape(start_marker(name)) + r".*?" + re.escape(end_marker(name)),
        re.S,
    )
    return pat.sub("", html)


def replace_between_markers(html: str, name: str, inner: str) -> str:
    """Replace the contents of an existing marked block with `inner`, keeping the
    markers. Raises if the block is absent (use insert_* for first-time write)."""
    if not has_markers(html, name):
        raise ValueError(f"markers {name!r} not found")
    pat = re.compile(
        re.escape(start_marker(name)) + r".*?" + re.escape(end_marker(name)), re.S
    )
    return pat.sub(lambda _: wrap_markers(name, inner), html, count=1)


# --- anchored / pattern insertion (first-time writes) -----------------------
def insert_after_anchor(html: str, anchor: str, text: str) -> str:
    """Insert `text` immediately after the single occurrence of `anchor`.

    Raises unless `anchor` occurs exactly once, so a drifted document fails loud
    instead of inserting in the wrong place.
    """
    n = html.count(anchor)
    if n != 1:
        raise ValueError(f"anchor must occur exactly once, found {n}: {anchor!r}")
    return html.replace(anchor, anchor + "\n" + text, 1)


def replace_first(html: str, pattern: str, replacement: str, flags=re.S) -> str:
    """Replace the first regex match. Raises if there is no match."""
    if not re.search(pattern, html, flags):
        raise ValueError(f"pattern not found: {pattern!r}")
    return re.sub(pattern, lambda _: replacement, html, count=1, flags=flags)


def upsert_marked_block(html: str, name: str, inner: str, *, anchor: str) -> str:
    """Idempotently place a marked block: replace it in place if the markers
    already exist, otherwise insert it after `anchor`."""
    block = wrap_markers(name, inner)
    if has_markers(html, name):
        return replace_between_markers(html, name, inner)
    return insert_after_anchor(html, anchor, block)


# --- CSS injection ----------------------------------------------------------
def inject_css(html: str, name: str, css_inner: str) -> str:
    """Idempotently inject a marked CSS block just before the first `</style>`."""
    html = strip_between_css_markers(html, name)
    if "</style>" not in html:
        raise ValueError("no </style> to inject CSS before")
    block = f"\n/* {name}-START */\n{css_inner}\n/* {name}-END */\n"
    return html.replace("</style>", block + "</style>", 1)


def strip_between_css_markers(html: str, name: str) -> str:
    """Remove a `/* NAME-START */ ... /* NAME-END */` CSS block if present,
    including whitespace on both sides so re-injection is exactly idempotent."""
    pat = re.compile(
        r"\s*/\* " + re.escape(name) + r"-START \*/.*?/\* " + re.escape(name) + r"-END \*/\s*",
        re.S,
    )
    return pat.sub("", html)


# --- section splitting ------------------------------------------------------
def slice_between(html: str, start: str, end: str) -> str:
    """Return the substring from `start` up to (not including) `end`."""
    i = html.index(start)
    j = html.index(end)
    return html[i:j]


def set_commit_label(html: str, sha: str) -> str:
    """Rewrite the doc's visible commit references (the masthead build-info block
    and the footer "Generated from commit ...") to `sha`. Used when a snapshot is
    copied forward to a new commit, so it self-identifies correctly instead of
    inheriting the source snapshot's sha."""
    build_info = f'''<div class="buildinfo">
    <span>commit <b>{sha}</b></span>
    <span><b>source-locked 2026</b> tariffs</span>
    <span><b>47 of 58</b> CA counties modeled</span>
    <span>working-paper artifact</span>
  </div>'''
    build_info_pattern = r'<div class="buildinfo">.*?</div>'
    if len(re.findall(build_info_pattern, html, flags=re.S)) != 1:
        raise ValueError("claims document must contain exactly one buildinfo block")
    html = re.sub(
        build_info_pattern,
        lambda _: build_info,
        html,
        count=1,
        flags=re.S,
    )
    html = re.sub(r"(Generated from commit )[0-9a-f]{6,40}", rf"\g<1>{sha}", html)
    return html


def strip_trailing_comment(s: str) -> str:
    """Trim a single trailing single-line HTML comment (e.g. a section banner)."""
    s = s.rstrip()
    s = re.sub(r"\s*<!--[^\n]*-->\s*$", "", s)
    return s.rstrip()


def split_by_anchors(html: str, anchors: List[str]) -> List[Tuple[str, str]]:
    """Split `html` at each anchor, returning (anchor, chunk) pairs where each
    chunk runs from its anchor to the next. Anchors must appear in order."""
    positions = []
    for a in anchors:
        positions.append((a, html.index(a)))
    out = []
    for k, (a, pos) in enumerate(positions):
        nxt = positions[k + 1][1] if k + 1 < len(positions) else len(html)
        out.append((a, html[pos:nxt]))
    return out
