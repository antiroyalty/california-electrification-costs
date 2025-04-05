from helpers import slugify_county_name

# Baseline Allowance for Residential Gas Rates (in therms/day)
# TODO: Ana, go more granular in the data so that we can more easily map to the PG&E and SCE climate zones / tarrif regions
# Gas rates also have baseline summer / winter allowances
# https://www.pge.com/tariffs/assets/pdf/tariffbook/GAS_SCHEDS_G-1.pdf
# https://www.pge.com/tariffs/assets/pdf/tariffbook/GAS_MAPS_Service_Area_Map.pdf
# https://www.cpuc.ca.gov/news-and-updates/all-news/breaking-down-pges-natural-gas-costs-and-rates
# Need mapping from county to service region
# Need other utilities gas rates
BASELINE_ALLOWANCES = {
    "PG&E": {
        "G-1": {
            "territories": {
                "P": {
                    "summer": 0.39,  # therms/day/dwelling unit
                    "winter_offpeak": 1.88,
                    "winter_onpeak": 2.19,
                },
                "Q": {
                    "summer": 0.56,
                    "winter_offpeak": 1.48,
                    "winter_onpeak": 2.00,
                },
                "R": {
                    "summer": 0.36,
                    "winter_offpeak": 1.24,
                    "winter_onpeak": 1.81,
                },
                "S": {
                    "summer": 0.39,
                    "winter_offpeak": 1.38,
                    "winter_onpeak": 1.94,
                },
                "T": {
                    "summer": 0.56,
                    "winter_offpeak": 1.31,
                    "winter_onpeak": 1.68,
                },
                "V": {
                    "summer": 0.59,
                    "winter_offpeak": 1.51,
                    "winter_onpeak": 1.71,
                },
                "W": {
                    "summer": 0.39,
                    "winter_offpeak": 1.14,
                    "winter_onpeak": 1.68,
                },
                "X": {
                    "summer": 0.49,
                    "winter_offpeak": 1.48,
                    "winter_onpeak": 2.00,
                },
                "Y&Z": {
                    "summer": 0.72,
                    "winter_offpeak": 2.22,
                    "winter_onpeak": 2.58,
                }
            }
        }
    },
    "SCE": { # Technically SoCalGas. They only have one residential plan.
        # https://www.cpuc.ca.gov/-/media/cpuc-website/files/uploadedfiles/cpuc_public_website/content/news_room/news_and_updates/cpuc-rates-fact-sheet-scg.pdf
        "GR": {
            "territories": {
                "Zone1": {
                    "summer": 1.69,
                    "winter_offpeak": 1.69,
                    "winter_onpeak": 1.69,
                },
                "Zone2": {
                    "summer": 1.823,
                    "winter_offpeak": 1.823,
                    "winter_onpeak": 1.823,
                }, 
                "Zone3": {
                    "summer": 2.950,
                    "winter_offpeak": 2.950,
                    "winter_onpeak": 2.950,
                }
            }
        }
    },
    # https://www.sdge.com/rates-and-regulations/current-and-effective-tariffs
    "SDG&E": { 
        "GR": {
            "territories": {
                "all": {
                    "summer": 0.359,
                    "winter_offpeak": 0.692,
                    "winter_onpeak": 1.233,
                }
            }
        }
    }
}

# Residential gas rates have baseline allowances:
# https://www.pge.com/tariffs/assets/pdf/tariffbook/GAS_SCHEDS_G-1.pdf
GAS_RATE_PLANS = {
    "PG&E": {
        "G-1": {
            "baseline": {
                "procurement_charge": 0.35402,  # per therm
                "transportation_charge": 1.94995,  # per therm
                "total_charge": 2.30397,  # per therm
            },
            "excess": {
                "procurement_charge": 0.35402,  # per therm
                "transportation_charge": 2.44371,  # per therm
                "total_charge": 2.79773,  # per therm
            }
        },
    }, # TODO: There is also a gas public purpose program (G-PPPS) that comes with surcharges
    "SCE": { # Technically SoCal Gas. https://www.socalgas.com/regulatory/documents/TariffBookUpdate.pdf
        "GR": {  # Standard Residential Service
            "baseline": {
                "procurement_charge": 0.43474,  # per therm
                "transmission_charge": 1.16715,  # per therm
                "total_charge": 1.60189,  # per therm
            },
            "excess": {
                "procurement_charge": 0.43474,  # per therm
                "transmission_charge": 1.65260,  # per therm
                "total_charge": 2.08734,  # per therm
            },
            "customer_charge": 0.16438,  # per meter per day
            "customer_charge_space_heating_winter": 0.33149,  # per meter per day (Nov-Apr)
        },
        # "GR-C": {  # Cross-over rate
        #     "baseline": {
        #         "procurement_charge": 0.43474,  # per therm
        #         "transmission_charge": 1.16715,  # per therm
        #         "total_charge": 1.60189,  # per therm
        #     },
        #     "excess": {
        #         "procurement_charge": 0.43474,  # per therm
        #         "transmission_charge": 1.65260,  # per therm
        #         "total_charge": 2.08734,  # per therm
        #     },
        #     "customer_charge": 0.16438,  # per meter per day
        #     "customer_charge_space_heating_winter": 0.33149,  # per meter per day (Nov-Apr)
        # },
        # "GT-R": {  # Core Aggregation Transportation (CAT)
        #     "baseline": {
        #         "transmission_charge": 1.16715,  # per therm
        #         "total_charge": 1.16715,  # per therm (no procurement charge)
        #     },
        #     "excess": {
        #         "transmission_charge": 1.65260,  # per therm
        #         "total_charge": 1.65260,  # per therm (no procurement charge)
        #     },
        #     "customer_charge": 0.16438,  # per meter per day
        #     "customer_charge_space_heating_winter": 0.33149,  # per meter per day (Nov-Apr)
        # }
    },
    "SDG&E": { # https://tariffsprd.sdge.com/sdge/tariffs/?utilId=SDGE&bookId=GAS&sectId=GAS-SCHEDS&tarfRateGroup=Core%20Services
        # blob:https://tariffsprd.sdge.com/12ee38a6-66ca-4986-b0ca-a297a9ff738c
        "GR": {
            "baseline": {
                "procurement_charge": 0.33310,  # per therm
                "transportation_charge": 2.04568,  # per therm
                "total_charge": 2.37878,  # per therm
            },
            "excess": {
                "procurement_charge": 0.33310,  # per therm
                "transportation_charge": 2.40579,  # per therm
                "total_charge": 2.73889,  # per therm
            },
            "minimum_bill_per_day": {
                "non_care": 0.13151,  # per day
                "care": 0.10521,      # per day
            },
            "seasonal_baseline_allowances": {
                "summer": 0.359,           # May to Oct (therms/day)
                "winter_on_peak": 1.233,   # Dec, Jan, Feb (therms/day)
                "winter_off_peak": 0.692   # Nov, Mar, Apr (therms/day)
            },
            "medical_baseline_additional": 0.822  # therms/day (Not used)
        },
        # "GR-C": {
        #     "baseline": {
        #         "procurement_charge": 0.43590,  # per therm
        #         "transportation_charge": 2.04568,  # per therm
        #         "total_charge": 2.48158,  # per therm
        #     },
        #     "excess": {
        #         "procurement_charge": 0.43590,  # per therm
        #         "transportation_charge": 2.40579,  # per therm
        #         "total_charge": 2.84169,  # per therm
        #     },
        #     "minimum_bill_per_day": {
        #         "non_care": 0.13151,  # per day
        #         "care": 0.10521,      # per day
        #     }
        # },
        # "GTC_GTCA": {
        #     "baseline": {
        #         "procurement_charge": None,  # not applicable
        #         "transportation_charge": 2.04568,  # per therm
        #         "total_charge": 2.04568,  # per therm
        #     },
        #     "excess": {
        #         "procurement_charge": None,  # not applicable
        #         "transportation_charge": 2.40579,  # per therm
        #         "total_charge": 2.40579,  # per therm
        #     },
        #     "minimum_bill_per_day": {
        #         "non_care": 0.13151,  # per day
        #         "care": 0.10521,      # per day
        #     }
        # }
    }
}

# Baseline allowance map
PGE_RATE_TERRITORY_COUNTY_MAPPING = {
    "T": [slugify_county_name(county) for county in ["Marin", "San Francisco", "San Mateo"]],
    "Q": [slugify_county_name(county) for county in ["Santa Cruz", "Monterey"]],
    "X": [slugify_county_name(county) for county in [
        "San Benito", "Santa Clara", 
        "Alameda", "Contra Costa", "Napa", "Sonoma", 
        "Mendocino", "Santa Barbara", "Solano", "Del Norte"
    ]], # TODO: Ana, Double check whether Solano and Del Norte are correctly placed here
    "P": [slugify_county_name(county) for county in [
        "Placer", "El Dorado", "Amador", "Calaveras", "Lake"
    ]],
    "S": [slugify_county_name(county) for county in [
        "Glenn", "Colusa", "Yolo", "Sutter", "Butte", "Yuba",
        "Sacramento", "Stanislaus", "San Joaquin", "Solano", "Sutter"
    ]],
    "R": [slugify_county_name(county) for county in [
        "Merced", "Fresno", "Madera", "Mariposa", "Tehama"
    ]],
    "Y&Z": [slugify_county_name(county) for county in [
        "Nevada", "Plumas", "Humboldt", "Trinity", "Tulare", "Lassen"
        "Lake", "Shasta", "Sierra", "Alpine", "Mono", "Toulumne"
    ]],
    "W": [slugify_county_name(county) for county in [
        "Kings",
        # Revisit these
        "Inyo", "Mono", "Sierra", "Plumas", "Modoc", "Sisikiyou"
    ]]
}

# Revisit these (SCE or SDGE): Kern, Inyo, Mono, Los Angeles, Ventura, San Bernadino, Sierra, Plumas, Modoc, Sisikiyou

# https://www.cpuc.ca.gov/-/media/cpuc-website/files/uploadedfiles/cpuc_public_website/content/news_room/news_and_updates/cpuc-rates-fact-sheet-scg.pdf
SCE_RATE_TERRITORY_COUNTY_MAPPING = {
    "Zone1": [slugify_county_name(county) for county in [
        "Riverside", "Orange", "Imperial", "Los Angeles", "Ventura", "Kern", "San Bernardino", "Santa Barbara", "Mono County", # TODO: Remove Mono County
    ]],
    "Zone2": [slugify_county_name(county) for county in [
        "San Luis Obispo", "Tulare", # Other Kings, Kern, Los Angeles zipcodes served by Zone2
    ]], 
    "Zone3": [] # Not big enough for any counties it seems
}

SDGE_RATE_TERRITORY_COUNTY_MAPPING = {
    "all": [slugify_county_name(county) for county in [
        "San Diego" # blob:https://tariffsprd.sdge.com/6fe61596-a59e-4788-ba88-9057f7ebb1d0
    ]]
}