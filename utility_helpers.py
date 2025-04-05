
from helpers import slugify_county_name


full_pge_counties = [ # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_MAPS_Service%20Area%20Map.pdf
    "Alameda County",
    "Alpine County",
    "Amador County",
    "Butte County",
    "Calaveras County",
    "Colusa County",
    "Contra Costa County",
    "Del Norte County",
    "El Dorado County",
    "Fresno County",
    "Glenn County",
    "Humboldt County",
    "Kings County",
    "Lake County",
    "Lassen County",
    "Madera County",
    "Marin County",
    "Mariposa County",
    "Mendocino County",
    "Merced County",
    "Monterey County",
    "Napa County",
    "Nevada County",
    "Placer County",
    "Plumas County",
    "Sacramento County",
    "San Benito County",
    "San Francisco County",
    "San Joaquin County",
    "San Mateo County",
    "Santa Barbara County", # Also SCE
    "Santa Clara County",
    "Santa Cruz County",
    "Shasta County",
    "Sierra County",
    "Siskiyou County",
    "Solano County",
    "Sonoma County",
    "Stanislaus County",
    "Sutter County",
    "Tehama County",
    "Trinity County",
    # "Tulare County",
    "Tuolumne County",
    "Yolo County",
    "Yuba County"
]

full_sce_counties = [
    "Mono County",
    "Inyo County",
    "San Bernardino County",
    "San Luis Obispo County",
    "Orange County",
    "Los Angeles County",
    "Ventura County",
    "Tulare County",
    "Riverside County",
    "Imperial County",
    "Kern County",
]

full_sdge_counties = [
    "San Diego County",
]

PGE_COUNTIES = [slugify_county_name(county) for county in full_pge_counties]
SCE_COUNTIES = [slugify_county_name(county) for county in full_sce_counties]
SDGE_COUNTIES = [slugify_county_name(county) for county in full_sdge_counties]


utility_to_counties = {
    # No California utilities serve: Del Norte, Siskiyou, Modoc
    # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_MAPS_Service%20Area%20Map.pdf
    "PG&E": PGE_COUNTIES, # note that PG&E doesn't serve: Del Norte, Siskiyou, Modoc, Trinity, Lassen, Sierra, Mono, Inyo, San Bernadino, Los Angeles, Ventura, Orange, Riverside, San Diego, Imperial
    "SCE": SCE_COUNTIES,
    "SDG&E": SDGE_COUNTIES,
}


def get_utility_for_county(county_slug):
    for utility, counties in utility_to_counties.items():
        if county_slug in counties:
            return utility