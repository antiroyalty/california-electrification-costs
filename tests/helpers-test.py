# tests/test_helpers.py

import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../')))

from helpers import slugify_county_name

@pytest.mark.parametrize("input_name,expected_slug", [
    # Typical cases with "County"
    ("Riverside County", "riverside"),
    ("Santa Clara County", "santa-clara"),
    ("Lake County", "lake"),
    ("San Luis Obispo County", "san-luis-obispo"),

    # Cases without "County"
    ("Trinity", "trinity"),
    ("Mono", "mono"),
    ("Marin", "marin"),

    # Leading and trailing whitespace
    ("  Orange County  ", "orange"),
    ("\tLos Angeles County\n", "los-angeles"),

    # Multiple spaces between words
    ("San Bernardino   County", "san-bernardino"),
    ("  San Diego    County  ", "san-diego"),

    # Mixed case letters
    ("ALAMEDA County", "alameda"),
    ("fresno COUNTY", "fresno"),
    ("Contra Costa County", "contra-costa"),

    # Empty string
    ("", ""),

    # Only "County"
    ("County", ""),

    # Special characters and punctuation
    ("St. Louis County", "st.-louis"),
    ("Prince George's County", "prince-george's"),

    # Numbers in the county name
    ("District of Columbia County", "district-of-columbia"),
    ("123 County", "123"),
    
    # Non-string inputs (should raise an error)
    # Uncomment the following lines if you handle non-string inputs
    # (None, TypeError),
    # (123, AttributeError),
])
def test_slugify_county_name(input_name, expected_slug):
    """
    Test the slugify_county_name function with various inputs.
    """
    if input_name is None or not isinstance(input_name, str):
        with pytest.raises(Exception):
            slugify_county_name(input_name)
    else:
        assert slugify_county_name(input_name) == expected_slug

def test_slugify_county_name_multiple_occurrences():
    """
    Test that multiple occurrences of "county" are all removed.
    """
    input_name = "County of County"
    expected_slug = "of"
    assert slugify_county_name(input_name) == expected_slug

def test_slugify_county_name_only_spaces():
    """
    Test that a string with only spaces returns an empty string.
    """
    input_name = "   "
    expected_slug = ""
    assert slugify_county_name(input_name) == expected_slug

def test_slugify_county_name_no_changes_needed():
    """
    Test that a county name that doesn't need changes is returned correctly.
    """
    input_name = "Alameda"
    expected_slug = "alameda"
    assert slugify_county_name(input_name) == expected_slug

def test_slugify_county_name_special_characters():
    """
    Test that special characters are handled correctly.
    """
    input_name = "Prince George's County"
    expected_slug = "prince-george's"
    assert slugify_county_name(input_name) == expected_slug

def test_slugify_county_name_hyphens():
    """
    Test that existing hyphens are preserved.
    """
    input_name = "San Luis-Obispo County"
    expected_slug = "san-luis-obispo"
    assert slugify_county_name(input_name) == expected_slug