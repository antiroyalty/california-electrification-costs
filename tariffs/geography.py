from __future__ import annotations

from dataclasses import dataclass

from helpers.main_helpers import slugify_county_name
from helpers.utility_helpers import get_utility_for_county

from .models import Utility


@dataclass(frozen=True)
class CountyServiceAssignment:
    """The one modeled utility service assignment for a county household.

    This preserves county as the research unit of analysis. It is deliberately
    separate from tariff prices: county selects a representative utility, while
    utility selects the NBT schedule. Climate zones are not tariff inputs.
    """

    county_slug: str
    utility: Utility
    assignment_method: str = "existing_research_dominant_iou_crosswalk"


def resolve_county_service_assignment(county_name_or_slug: str) -> CountyServiceAssignment:
    county_slug = slugify_county_name(county_name_or_slug)
    utility = get_utility_for_county(county_slug)
    if utility is None:
        raise KeyError(f"No representative utility assignment for county {county_slug}")
    return CountyServiceAssignment(county_slug=county_slug, utility=Utility.parse(utility))
