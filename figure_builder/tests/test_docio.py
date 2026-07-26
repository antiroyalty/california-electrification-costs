"""Unit tests for the pure HTML/document primitives.

These are the parts that used to be regex soup buried in one-off scripts. They
are pure string-in/string-out, so they test fast and deterministically.
"""
import re

import pytest

from figure_builder import docio


def test_wrap_and_has_markers():
    wrapped = docio.wrap_markers("BLOCK", "hi")
    assert wrapped == "<!-- BLOCK-START -->\nhi\n<!-- BLOCK-END -->"
    assert docio.has_markers(wrapped, "BLOCK")
    assert not docio.has_markers("plain", "BLOCK")


def test_replace_between_markers_is_idempotent():
    html = "a " + docio.wrap_markers("B", "old") + " z"
    once = docio.replace_between_markers(html, "B", "new")
    twice = docio.replace_between_markers(once, "B", "new")
    assert "new" in once and "old" not in once
    assert once == twice  # idempotent
    assert once.count("<!-- B-START -->") == 1


def test_replace_between_markers_absent_raises():
    with pytest.raises(ValueError):
        docio.replace_between_markers("no markers here", "B", "x")


def test_upsert_inserts_first_time_then_replaces():
    html = "intro ANCHOR tail"
    first = docio.upsert_marked_block(html, "M", "body1", anchor="ANCHOR")
    assert "ANCHOR" in first and docio.has_markers(first, "M")
    # second call must not duplicate; it replaces in place and ignores anchor
    second = docio.upsert_marked_block(first, "M", "body2", anchor="ANCHOR")
    assert second.count("<!-- M-START -->") == 1
    assert "body2" in second and "body1" not in second


def test_insert_after_anchor_requires_unique_anchor():
    with pytest.raises(ValueError):
        docio.insert_after_anchor("X and X", "X", "y")  # two anchors
    with pytest.raises(ValueError):
        docio.insert_after_anchor("nope", "X", "y")     # zero anchors
    assert docio.insert_after_anchor("aXb", "X", "-Y-") == "aX\n-Y-b"


def test_strip_between_markers_roundtrip():
    inner = docio.wrap_markers("Z", "content")
    html = "before\n" + inner + "\nafter"
    stripped = docio.strip_between_markers(html, "Z")
    assert "content" not in stripped
    assert "before" in stripped and "after" in stripped
    # stripping when absent is a no-op
    assert docio.strip_between_markers("plain", "Z") == "plain"


def test_inject_css_is_idempotent():
    html = "<style>body{}</style>"
    once = docio.inject_css(html, "MECH-CSS", ".x{color:red}")
    twice = docio.inject_css(once, "MECH-CSS", ".x{color:red}")
    assert once == twice
    assert once.count("/* MECH-CSS-START */") == 1
    assert once.endswith("</style>")


def test_replace_first_raises_without_match():
    with pytest.raises(ValueError):
        docio.replace_first("abc", r"z+", "Q")
    assert docio.replace_first("a11b22", r"\d+", "N") == "aNb22"


def test_strip_trailing_comment():
    assert docio.strip_trailing_comment("body  <!-- banner -->  ") == "body"
    assert docio.strip_trailing_comment("no comment") == "no comment"


def test_slice_between():
    html = "AAsectionBBrest"
    assert docio.slice_between(html, "section", "rest") == "sectionBB"


def test_figure_html_shape():
    out = docio.figure_html("BASE64", "a caption", "alt text")
    assert 'src="data:image/png;base64,BASE64"' in out
    assert "<figcaption>a caption</figcaption>" in out
    assert 'alt="alt text"' in out
