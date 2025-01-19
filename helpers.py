# helpers.py

def slugify_county_name(county_name: str) -> str:
    """
    Takes a county name like "Santa Clara County" or "Riverside County"
    and converts it to a slug: "santa-clara", "riverside", etc.
    
    Example transformations:
      "Riverside County"   -> "riverside"
      "Santa Clara County" -> "santa-clara"
      " Lake County  "     -> "lake"
    """
    if not isinstance(county_name, str):
        raise TypeError(f"Expected a string for county_name, got {type(county_name).__name__}")
    
    return (
        county_name.lower()
                   .replace("county", "")
                   .strip()
                   .replace(" ", "-")
    )