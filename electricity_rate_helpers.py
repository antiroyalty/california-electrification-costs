from helpers import slugify_county_name

# from dataclasses import dataclass

# @dataclass
# class County:
#     name: str
#     utility: str

#     @property
#     def slug(self):
#         return slugify_county_name(self.name)
    
# class CountyStore:
#     all_counties = []

#     def create(self, name, utility):
#         county = County(name=name, utility=utility)
#         self.all_counties.append(county)
#         return county
    
#     def get_by_slug(self, slug):
#         for county in self.all_counties:
#             if county.slug == slug:
#                 return county
#         return None
    
#     def get_by_name(self, name):
#         for county in self.all_counties:
#             if county.name == name:
#                 return county
#         return None
    
#     def get_by_utility(self, utility):
#         return [county for county in self.all_counties if county.utility == utility]

# county_store = CountyStore()

# county_store.create("Alameda County", "PG&E")
# county_store.create("Alpine County", "PG&E")
# county_store.create("Amador County", "PG&E")


full_pge_counties = [ # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_MAPS_Service%20Area%20Map.pdf
    "Alameda County",
    "Alpine County",
    "Amador County",
    "Butte County",
    "Calaveras County",
    "Colusa County",
    "Contra Costa County",
    "El Dorado County",
    "Fresno County",
    "Glenn County",
    "Humboldt County",
    "Kern County",
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
    "San Luis Obispo County",
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
    "Orange County",
    "Los Angeles County",
    "Ventura County",
    "Tulare County",
]

full_sdge_counties = [
    "San Diego County",
    "Riverside County",
    "Imperial County",
]

PGE_COUNTIES = [slugify_county_name(county) for county in full_pge_counties]
SCE_COUNTIES = [slugify_county_name(county) for county in full_sce_counties]
SDGE_COUNTIES = [slugify_county_name(county) for county in full_sdge_counties]

BASELINE_ALLOWANCES = {
    "PGE": {
        "E-TOU-C": {
            "territories": {
                "P": {"summer": 13.5, "winter": 11.0},
                "Q": {"summer": 9.8,  "winter": 11.0},
                "R": {"summer": 17.7, "winter": 10.4},
                "S": {"summer": 15.0, "winter": 10.2},
                "T": {"summer": 6.5,  "winter": 7.5},
                "V": {"summer": 7.1,  "winter": 8.1},
                "W": {"summer": 19.2, "winter": 9.8},
                "X": {"summer": 9.8,  "winter": 9.7},
                "Y": {"summer": 10.5, "winter": 11.1},
                "Z": {"summer": 5.9,  "winter": 7.8},
            }
        }
    },
    # 
    # Baseline allocations: https://www.sce.com/sites/default/files/inline-files/Baseline_Region_Map.pdf
    "SCE": {
        "TOU-D-4-9PM": {
            "territories": {
                # "Baseline region number": "daily_kwh_allocation": {"summer": "daily kWh allocation", "winter": "daily kWh allocation"}, "all_electric_allocation": {"summer": "all electric kWh allocation", "winter": "all electric kWh allocation"}
                # Summer = June - September, Winter = October - May
                "5": {"daily_kwh_allocation": {"summer": 17.0, "winter": 18.4}, "all_electric_allocation": {"summer": 16.7, "winter": 27.0}}, # Santa Barbara Coastal
                "6": {"daily_kwh_allocation": {"summer": 11.4, "winter": 11.0}, "all_electric_allocation": {"summer": 8.7, "winter": 12.6}}, # Coastal, Catalina Island
                "8": {"daily_kwh_allocation": {"summer": 12.8, "winter": 10.3}, "all_electric_allocation": {"summer": 9.9, "winter": 12.3}}, # Parts of LA
                "9": {"daily_kwh_allocation": {"summer": 16.9, "winter": 12.0}, "all_electric_allocation": {"summer": 12.5, "winter": 13.9}}, # Parts of Orange County
                "10": {"daily_kwh_allocation": {"summer": 19.3, "winter": 12.1}, "all_electric_allocation": {"summer": 15.9, "winter": 16.4}}, # Parts of Riverside, San Bernadino
                "13": {"daily_kwh_allocation": {"summer": 22.2, "winter": 12.2}, "all_electric_allocation": {"summer": 24.2, "winter": 23.0}}, # Other half of Tulare
                "14": {"daily_kwh_allocation": {"summer": 19.2, "winter": 11.9}, "all_electric_allocation": {"summer": 18.5, "winter": 21.1}}, # Mostly San Bernadino
                "15": {"daily_kwh_allocation": {"summer": 45, "winter": 9.7}, "all_electric_allocation": {"summer": 24.0, "winter": 17.4}}, # Mostly mountains south of Inyo, Joshua Tree
                "16": {"daily_kwh_allocation": {"summer": 14.7, "winter": 12.4}, "all_electric_allocation": {"summer": 13.5, "winter": 23.2}}, # Roughly: Mono, Inyo, parts of Tulare, Kern, LA, San Bernadino
            }
        }
    },
    # https://www.sdge.com/baseline-allowance-calculator
    # "SDGE": {
    #     TODO: Ana
    # },
}

PGE_RATE_PLANS ={
        "E-TOU-C": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-C.pdf
            "summer": {
                "weekdays": {
                    "peak": 0.60729,
                    "offPeak": 0.50429,
                    "peakHours": list(range(16, 21)),  # 4:00 p.m. to 9:00 p.m.
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.10135,
                    # Defaulting to territory T baseline allowance;
                    # In practice this should be chosen per the customer's territory
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"],
                    "fixedCharge": 0.00,
                },
                "weekends": { # same as weekdays for E-TOU-C
                    "peak": 0.60729,
                    "offPeak": 0.50429,
                    "peakHours": list(range(16, 21)),  # 4:00 p.m. to 9:00 p.m.
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.10135,
                    # Defaulting to territory T baseline allowance;
                    # In practice this should be chosen per the customer's territory
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"],
                    "fixedCharge": 0.00,
                }
            },
            "winter": {
                "weekdays": {
                    "peak": 0.49312,
                    "offPeak": 0.46312,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.10135,
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["winter"],
                    "fixedCharge": 0.00,
                },
                "weekends": { # same as weekdays for E-TOU-C
                    "peak": 0.49312,
                    "offPeak": 0.46312,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.10135,
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["winter"],
                    "fixedCharge": 0.00,
                }
            },
        },
        "E-TOU-D": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-D.pdf
            "summer": {
                "weekdays": {
                    "peak": 0.56462, 
                    "offPeak": 0.42966, 
                    "peakHours": [17, 18, 19], 
                    "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                    "fixedCharge": 0.00,
                },
                "weekends": { # different from weekdays
                    "peak": 0,
                    "offPeak": 0.42966,
                    "peakHours": [],
                    "offPeakHours": [h for h in range(24)], # everything is off peak on the weekends
                    "fixedCharge": 0.00,
                },
            },
            "winter": {
                "weekdays": {
                    "peak": 0.47502, 
                    "offPeak": 0.43641, 
                    "peakHours": [17, 18, 19], 
                    "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                    "fixedCharge": 0.00,
                },
                "weekends": { # different from weekdays
                    "peak": 0, 
                    "offPeak": 0.43641, 
                    "peakHours": [], 
                    "offPeakHours": [h for h in range(24)], # everything is off peak on the weekends
                    "fixedCharge": 0.00,
                },
            },
        },
        "EV2-A": {  # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_EV2%20(Sch).pdf EV2 bills are issued as EV2-A
            "summer": {
                "weekdays": {
                    "peak": 0.61590,      # Peak rate ($ per kWh)
                    "partPeak": 0.50541,  # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.30339,   # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.39167,
                },
                "weekends": { # same as weekdays for EV2-A
                    "peak": 0.61590,      # Peak rate ($ per kWh)
                    "partPeak": 0.50541,  # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.30339,   # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.39167,
                },
            },
            "winter": {
                "weekdays": {
                    "peak": 0.48879,      # Peak rate ($ per kWh)
                    "partPeak": 0.47209,  # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.30339,   # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.39167,
                },
                "weekends": {
                    "peak": 0.48879,      # Peak rate ($ per kWh)
                    "partPeak": 0.47209,  # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.30339,   # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.39167,
                },
            },
            # "fixedCharge": 0.39167, # Delivery Minimum Bill Amount per meter per day:
        },
        "E-ELEC": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf
            "summer": {
                "weekdays": {
                    "peak": 0.60728,
                    "partPeak": 0.44540, 
                    "offPeak": 0.38872,   
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.49281 # Base Services Charge per meter per day
                },
                "weekends": { # same as weekdays
                    "peak": 0.60728,      # Peak rate (4:00–9:00 p.m.)
                    "partPeak": 0.44540,  # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                    "offPeak": 0.38872,   # Off-Peak rate (all other hours)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.49281 # Base Services Charge per meter per day
                },
            },
            "winter": {
                "weekdays": {
                    "peak": 0.37577,      # Peak rate (4:00–9:00 p.m.)
                    "partPeak": 0.35368,  # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                    "offPeak": 0.33982,   # Off-Peak rate (all other hours)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.49281 # Base Services Charge per meter per day
                },
                "weekends": { # same as weekdays
                    "peak": 0.37577,      # Peak rate (4:00–9:00 p.m.)
                    "partPeak": 0.35368,  # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                    "offPeak": 0.33982,   # Off-Peak rate (all other hours)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.49281,
                },
            }
        },
    }

SCE_RATE_PLANS = {
    "TOU-D-4-9PM": {
            "summer": { # June - September
                "weekdays": {
                    "peak": 0.59,
                    "offPeak": 0.36,
                    "peakHours": list(range(16, 21)),  # 4:00 pm to 9:00 pm
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.03,         # Daily basic charge
                },
                "weekends": {
                    "peak": 0.48,
                    "offPeak": 0.36,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.03,         # Daily basic charge
                },
                "weekdaysAfterBaselineCredit": {
                    "peak": 0.50,
                    "offPeak": 0.27,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.03,         # Daily basic charge
                },
                "weekendAfterBaselineCredit": {
                    "peak": 0.39,
                    "offPeak": 0.27,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.03,         # Daily basic charge
                },
            },
            "winter": { # October - May
                "weekdays": {
                    "peak": 0.52,
                    "offPeak": 0.39,
                    "superOffPeak": 0.35,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.03,         # Daily basic charge
                },
                "weekends": { # Same as weekdays in the winter
                    "peak": 0.52,
                    "offPeak": 0.39,
                    "superOffPeak": 0.35,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.03,         # Daily basic charge
                },
                "weekdaysAfterBaselineCredit": {
                    "peak": 0.43,
                    "offPeak": 0.30,
                    "superOffPeak": 0.26,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.03,         # Daily basic charge
                },
                "weekendsAfterBaselineCredit": { # Same as weekdaysAfterBaselineCredit in the winter
                    "peak": 0.43,
                    "offPeak": 0.30,
                    "superOffPeak": 0.26,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.03,         # Daily basic charge
                }
            },
            "fixedCharge": 0.03,         # Daily basic charge
            "minimumDailyCharge": 0.35,  # Minimum daily charge
            "baseline_credit": 0.09,
        },
    "TOU-D-5-8PM": { # https://www.sce.com/residential/rates/Time-Of-Use-Residential-Rate-Plans
        # From website: "Better for customers who end the night early. May benefit those who are home during the day and tend to live in smaller rented dwellings."
        "summer": { # June - September
            "weekdays": {
                "peak": 0.74,      # Highest rate during peak period
                "offPeak": 0.36,   # Off-peak rate
                "peakHours": list(range(17, 20)),  # 5:00–8:00 p.m.
                "offPeakHours": [h for h in range(24) if h not in range(17, 20)],
                "fixedCharge": 0.03,
            },
            "weekends": {
                "peak": 0.55,
                "offPeak": 0.36,
                "peakHours": list(range(17, 20)),
                "offPeakHours": [h for h in range(24) if h not in range(17, 20)],
                "fixedCharge": 0.03,
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.65,      # Lower peak rate
                "offPeak": 0.27,   # Lower off-peak rate
                "peakHours": [17, 18, 19],  # 5:00–8:00 p.m.
                "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                "fixedCharge": 0.03,
            },
            "weekendAfterBaselineCredit": {
                "peak": 0.46,
                "offPeak": 0.27,
                "peakHours": [17, 18, 19],
                "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                "fixedCharge": 0.03,
            },
        },
        "winter": { # October - May
            "weekdays": {
                "midPeak": 0.61,         # Applies from 8:00 a.m. to 5:00 p.m.
                "offPeak": 0.40,         # Applies during hours outside mid‑peak
                "superOffPeak": 0.34,    # Lowest rate during qualifying conditions
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.03,
            },
            "weekends": {
                "midPeak": 0.61,         # Applies from 8:00 am to 5:00 pm
                "offPeak": 0.40,         # Applies during hours outside mid‑peak
                "superOffPeak": 0.34,    # Lowest rate during qualifying conditions
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.03,
            },
            "weekdaysAfterBaselineCredit": {
                "midPeak": 0.52,         # Applies from 8:00 am to 5:00 pm
                "offPeak": 0.31,         # 8pm - 8am (Overnight)
                "superOffPeak": 0.25,    # 8am - 5pm (Sunshine hours)
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.03,
            },
            "weekendAfterBaselineCredit": {
                "midPeak": 0.52,         # Applies from 8:00 am to 5:00 pm
                "offPeak": 0.31,         # 8pm - 8am (Overnight)
                "superOffPeak": 0.25,    # 8am - 5pm (Sunshine hours)
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.03,
            },
        },
        "minimumDailyCharge": 0.35,
        "baseline_credit": 0.09,
    },
    "TOU-D-PRIME": {
        "summer": {
            "weekdays": {
                "peak": 0.53,
                "offPeak": 0.24,
                "peakHours": list(range(16, 21)),  # 4:00 pm to 9:00 pm
                "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                "fixedCharge": 0.53, # Aka Daily Basic Charge
            },
            "weekends": {
                "peak": 0.38,
                "offPeak": 0.26,
                "peakHours": list(range(16, 21)),
                "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                "fixedCharge": 0.53, # Aka Daily Basic Charge
            }
        },
        "winter": {
            "weekdays": {
                "peak": 0.53,
                "offPeak": 0.24,
                "superOffPeak": 0.24, # Same as offpeak in April 2025
                "peakHours": [16, 17, 18, 19, 20], # Evening
                "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                "fixedCharge": 0.53, # Aka Daily Basic Charge
            },
            "weekends": { # same as weekdays April 2025
                "peak": 0.53,
                "offPeak": 0.24,
                "superOffPeak": 0.24, # Same as offpeak in April 2025
                "peakHours": [16, 17, 18, 19, 20], # Evening
                "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                "fixedCharge": 0.53, # Aka Daily Basic Charge
            }
        },
        "minimumDailyCharge": 0,
        "baseline_credit": 0,
    }
}

SDGE_RATE_PLANS = {
    "TOU-DR1": { # https://www.sdge.com/residential/pricing-plans/about-our-pricing-plans/whenmatters
        "summer": {
            "weekdays": {
                "peak": 0.458, # SDGE Also has a CCA customer plan, but I don't model this because SDGE only has partial information (SDGE delivery charges only). "CCA customers must also pay for electric generation at prices determined by the CCA. For CCA electric generation prices, please contact your CCA." 
                "offPeak": 0.393,
                "superOffPeak": 0.375,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekends": {
                "peak": 0.458, # prices same as weekday, hours are different
                "offPeak": 0.393,
                "superOffPeak": 0.375,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [14, 15, 21, 22, 23],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.564,
                "offPeak": 0.499,
                "superOffPeak": 0.48,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13], # Same hours as below baseline credit
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekendsAfterBaselineCredit": {
                "peak": 0.564,
                "offPeak": 0.499,
                "superOffPeak": 0.48,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [14, 15, 21, 22, 23],
            },
        },
        "winter": { # Identical for SDGE. There are exceptions for March and April but hard to implement
            "weekdays": {
                "peak": 0.458, # SDGE Also has a CCA customer plan, but I don't model this because SDGE only has partial information (SDGE delivery charges only). "CCA customers must also pay for electric generation at prices determined by the CCA. For CCA electric generation prices, please contact your CCA." 
                "offPeak": 0.393,
                "superOffPeak": 0.375,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekends": {
                "peak": 0.458, # prices same as weekday, hours are different
                "offPeak": 0.393,
                "superOffPeak": 0.375,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [14, 15, 21, 22, 23],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.564,
                "offPeak": 0.499,
                "superOffPeak": 0.48,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13], # Same hours as below baseline credit
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekendsAfterBaselineCredit": {
                "peak": 0.564,
                "offPeak": 0.499,
                "superOffPeak": 0.48,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [14, 15, 21, 22, 23],
            },
        },
    },
    "TOU-DR2": {
        "summer": {
            "weekdays": {
                "peak": 0.458,
                "offPeak": 0.385,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
            "weekends": { # Same for weekdays and weekends
                "peak": 0.458,
                "offPeak": 0.385,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.564,
                "offPeak": 0.490,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
            "weekendsAfterBaselineCredit": { # Same as weekdays 
                "peak": 0.564,
                "offPeak": 0.490,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
        },
        "winter": { # same as summer
            "weekdays": {
                "peak": 0.458,
                "offPeak": 0.385,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
            "weekends": { # Same for weekdays and weekends
                "peak": 0.458,
                "offPeak": 0.385,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.564,
                "offPeak": 0.490,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
            "weekendsAfterBaselineCredit": { # Same as weekdays 
                "peak": 0.564,
                "offPeak": 0.490,
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [h for h in range(24) if h not in [16, 17, 18, 19, 20]],
            },
        }
    },
    "TOU-DR-P": { # "Has Reduce Your Use event days where you may be called upon to conserve energy"
        "summer": {
            "weekdays": {
                "peak": 0.442,
                "offPeak": 0.384,
                "superOffPeak": 0.368,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
            "weekends": { # same as weekdays
                "peak": 0.442,
                "offPeak": 0.384,
                "superOffPeak": 0.368,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.547,
                "offPeak": 0.49,
                "superOffPeak": 0.473,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
            "weekendsAfterBaselineCredit": {
                "peak": 0.547,
                "offPeak": 0.49,
                "superOffPeak": 0.473,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
        },
        "winter": { # Let's say it's the same as summer, though technically March and April are different
            "weekdays": {
                "peak": 0.442,
                "offPeak": 0.384,
                "superOffPeak": 0.368,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
            "weekends": { # same as weekdays
                "peak": 0.442,
                "offPeak": 0.384,
                "superOffPeak": 0.368,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.547,
                "offPeak": 0.49,
                "superOffPeak": 0.473,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
            "weekendsAfterBaselineCredit": {
                "peak": 0.547,
                "offPeak": 0.49,
                "superOffPeak": 0.473,
                "reduceYourUse": 1.16, # Price during Reduce Your Use event days
                "peakHours": [16, 17, 18, 19, 20],
                "reduceYourUseHours": [16, 17, 18, 19, 20], # same as peak hours, but only issued for up to 18 days of the year
                "offPeakHours": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 21, 22, 23],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
            },
        },
    },
    "TOU-ELEC": { # https://www.sdge.com/sites/default/files/regulatory/2-1-25%20Schedule%20TOU-ELEC%20Total%20Rates%20Table.pdf
        "summer": { # https://www.sdge.com/residential/pricing-plans/about-our-pricing-plans/whenmatters
            "weekdays": {
                "onPeak": 0.44,
                "offPeak": 0.332,
                "superOffPeak": 0.298,
                "onPeakHours": [16, 17, 18, 19, 20],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
                "offPeakHours": [14, 15, 21, 22, 23],
                "fixedCharge": 0.53333, # 16.00/30: Monthly $16 fixed charge, divide by 30 days in a month on avg
            },
            "weekends": {
                "onPeak": 0.44,
                "offPeak": 0.332,
                "superOffPeak": 0.298,
                "onPeakHours": [16, 17, 18, 19, 20],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "offPeakHours": [14, 15, 21, 22, 23],
                "fixedCharge": 0.53333, # 16.00/30: Monthly $16 fixed charge, divide by 30 days in a month on avg
            }
        },
        "winter": { # Consider it to be same as summer, though technically March and April have different behavior
            "weekdays": {
                "onPeak": 0.44,
                "offPeak": 0.332,
                "superOffPeak": 0.298,
                "onPeakHours": [16, 17, 18, 19, 20],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6],
                "offPeakHours": [14, 15, 21, 22, 23],
                "fixedCharge": 0.53333, # 16.00/30: Monthly $16 fixed charge, divide by 30 days in a month on avg
            },
            "weekends": {
                "onPeak": 0.44,
                "offPeak": 0.332,
                "superOffPeak": 0.298,
                "onPeakHours": [16, 17, 18, 19, 20],
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "offPeakHours": [14, 15, 21, 22, 23],
                "fixedCharge": 0.53333, # 16.00/30: Monthly $16 fixed charge, divide by 30 days in a month on avg
            }
        },
    },
    "Standard-DR-Pricing-Plan": {
        "summer": {
            "weekdays": {
                "peak": 0.512,
                "offPeak": 0, 
                "superOffPeak": 0, # we're gonna call this partPeak even though it's more like offPeak. But this naming allows us to align with PG&E's naming.
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],
            },
            "weekends": { # same as weekdays
                "peak": 0.512,
                "offPeak": 0,
                "superOffPeak": 0,
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.407,
                "offPeak": 0,
                "superOffPeak": 0,
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],

            },
            "weekendsAfterBaselineCredit": { # same as weekdays
                "peak": 0.512,
                "offPeak": 0,
                "superOffPeak": 0,
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],
            }
        },
        "winter": { # same as summer
            "weekdays": {
                "peak": 0.512,
                "offPeak": 0,
                "superOffPeak": 0,
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],
            },
            "weekends": { # same as weekdays
                "peak": 0.512,
                "offPeak": 0,
                "superOffPeak": 0,
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.407,
                "offPeak": 0,
                "superOffPeak": 0,
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],

            },
            "weekendsAfterBaselineCredit": { # same as weekdays
                "peak": 0.512,
                "offPeak": 0,
                "superOffPeak": 0,
                "peakHours": [h for h in range(24)], # all hours,
                "offPeakHours": [],
                "superOffPeakHours": [],
            },
        },
    }
}