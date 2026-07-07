from helpers.main_helpers import slugify_county_name

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
            # Rates updated to March 1, 2026 (AB 205 restructuring).
            # Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
            # Above-baseline rates used as primary (baseline_credit subtracted for below-baseline usage).
            # Summer: peak above 52¢, peak below 44¢, off-peak above 40¢, off-peak below 32¢ → credit = 8¢
            # Winter: peak above 40¢, peak below 32¢, off-peak above 37¢, off-peak below 29¢ → credit = 8¢
            "summer": {
                "weekdays": {
                    "peak": 0.52,
                    "offPeak": 0.40,
                    "peakHours": list(range(16, 21)),  # 4:00 p.m. to 9:00 p.m.
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.08,
                    # Defaulting to territory T baseline allowance;
                    # In practice this should be chosen per the customer's territory
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"],
                    "fixedCharge": 0.00,
                },
                "weekends": { # same as weekdays for E-TOU-C
                    "peak": 0.52,
                    "offPeak": 0.40,
                    "peakHours": list(range(16, 21)),  # 4:00 p.m. to 9:00 p.m.
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.08,
                    # Defaulting to territory T baseline allowance;
                    # In practice this should be chosen per the customer's territory
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["summer"],
                    "fixedCharge": 0.00,
                }
            },
            "winter": {
                "weekdays": {
                    "peak": 0.40,
                    "offPeak": 0.37,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.08,
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["winter"],
                    "fixedCharge": 0.00,
                },
                "weekends": { # same as weekdays for E-TOU-C
                    "peak": 0.40,
                    "offPeak": 0.37,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "baseline_credit": 0.08,
                    "baseline_allowance": BASELINE_ALLOWANCES["PGE"]["E-TOU-C"]["territories"]["T"]["winter"],
                    "fixedCharge": 0.00,
                }
            },
        },
        "E-TOU-D": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-TOU-D.pdf
            # Rates updated to March 1, 2026 (AB 205 restructuring).
            # Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
            "summer": {
                "weekdays": {
                    "peak": 0.48,
                    "offPeak": 0.34,
                    "peakHours": [17, 18, 19],
                    "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                    "fixedCharge": 0.00,
                },
                "weekends": { # different from weekdays
                    "peak": 0,
                    "offPeak": 0.34,
                    "peakHours": [],
                    "offPeakHours": [h for h in range(24)], # everything is off peak on the weekends
                    "fixedCharge": 0.00,
                },
            },
            "winter": {
                "weekdays": {
                    "peak": 0.39,
                    "offPeak": 0.35,
                    "peakHours": [17, 18, 19],
                    "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                    "fixedCharge": 0.00,
                },
                "weekends": { # different from weekdays
                    "peak": 0,
                    "offPeak": 0.35,
                    "peakHours": [],
                    "offPeakHours": [h for h in range(24)], # everything is off peak on the weekends
                    "fixedCharge": 0.00,
                },
            },
        },
        "EV2-A": {  # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_EV2%20(Sch).pdf EV2 bills are issued as EV2-A
            # Rates updated to March 1, 2026 (AB 205 restructuring).
            # Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
            # fixedCharge = Base Services Charge, Tier 3 ($0.79343/day), per ELEC_SCHEDS_EV2 (Sch).pdf.
            # Tier 3 is the standard rate for customers who don't qualify for CARE (Tier 1) or FERA (Tier 2).
            # The paper models homeowners installing solar — higher-income assumption → Tier 3.
            # Tier 1: $0.19713/day, Tier 2: $0.39688/day, Tier 3: $0.79343/day (March 1, 2026).
            "summer": {
                "weekdays": {
                    "peak": 0.54,         # Peak rate ($ per kWh)
                    "partPeak": 0.43,     # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.23,      # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,  # Base Services Charge, Tier 3
                },
                "weekends": { # same as weekdays for EV2-A (peak every day per tariff)
                    "peak": 0.54,         # Peak rate ($ per kWh)
                    "partPeak": 0.43,     # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.23,      # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,
                },
            },
            "winter": {
                "weekdays": {
                    "peak": 0.41,         # Peak rate ($ per kWh)
                    "partPeak": 0.39,     # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.23,      # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,
                },
                "weekends": {
                    "peak": 0.41,         # Peak rate ($ per kWh)
                    "partPeak": 0.39,     # Partial-Peak rate ($ per kWh)
                    "offPeak": 0.23,      # Off-Peak rate ($ per kWh)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,
                },
            },
        },
        "EV-B": {  # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_EV%20(Sch).pdf
            # Rates: March 1, 2026.
            # Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
            # Weekday peak: 2–9 pm (hours 14–20).
            # Weekday partial-peak: 7 am–2 pm and 9–11 pm (hours 7–13, 21–22).
            # Weekend peak: 3–7 pm (hours 15–18). NO partial-peak on weekends.
            # Off-peak: all other hours.
            # Meter charge: $0.04928/day (flat; not income-tiered like EV2-A/E-ELEC).
            # Source for meter charge + weekend time periods: ELEC_SCHEDS_EV (Sch).pdf
            "summer": {
                "weekdays": {
                    "peak": 0.62,
                    "partPeak": 0.38,
                    "offPeak": 0.26,
                    "peakHours": list(range(14, 21)),       # 2:00 p.m. to 9:00 p.m.
                    "partPeakHours": list(range(7, 14)) + [21, 22],  # 7 am–2 pm and 9–11 pm
                    "offPeakHours": list(range(0, 7)) + [23],        # midnight–7 am and 11 pm–midnight
                    "fixedCharge": 0.04928,  # Total Meter Charge Per Day (flat)
                },
                "weekends": {  # Weekend peak is 3–7 pm only; no partial-peak
                    "peak": 0.62,
                    "offPeak": 0.26,
                    "peakHours": list(range(15, 19)),                 # 3:00 p.m. to 7:00 p.m.
                    "offPeakHours": [h for h in range(24) if h not in range(15, 19)],
                    "fixedCharge": 0.04928,
                },
            },
            "winter": {
                "weekdays": {
                    "peak": 0.44,
                    "partPeak": 0.31,
                    "offPeak": 0.24,
                    "peakHours": list(range(14, 21)),
                    "partPeakHours": list(range(7, 14)) + [21, 22],
                    "offPeakHours": list(range(0, 7)) + [23],
                    "fixedCharge": 0.04928,
                },
                "weekends": {  # Weekend peak is 3–7 pm only; no partial-peak
                    "peak": 0.44,
                    "offPeak": 0.24,
                    "peakHours": list(range(15, 19)),
                    "offPeakHours": [h for h in range(24) if h not in range(15, 19)],
                    "fixedCharge": 0.04928,
                },
            },
        },
        "E-ELEC": { # https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_E-ELEC.pdf
            # Rates updated to March 1, 2026 (AB 205 restructuring).
            # Source: data/utility-rates/pge/pge-residential-electric-rate-plan-pricing.pdf
            # Winter peak (4-9pm) MEDIUM confidence — not clearly labeled in PDF; 32¢ is best read.
            # fixedCharge = Base Services Charge, Tier 3 ($0.79343/day), per ELEC_SCHEDS_E-ELEC.pdf.
            # Same tier structure as EV2-A; Tier 3 used (standard non-CARE/FERA customer).
            # Tier 1: $0.19713/day, Tier 2: $0.39688/day, Tier 3: $0.79343/day (March 1, 2026).
            "summer": {
                "weekdays": {
                    "peak": 0.55,         # Peak rate (4:00–9:00 p.m.)
                    "partPeak": 0.39,     # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                    "offPeak": 0.33,      # Off-Peak rate (all other hours)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,  # Base Services Charge, Tier 3
                },
                "weekends": { # same as weekdays
                    "peak": 0.55,         # Peak rate (4:00–9:00 p.m.)
                    "partPeak": 0.39,     # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                    "offPeak": 0.33,      # Off-Peak rate (all other hours)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,
                },
            },
            "winter": {
                "weekdays": {
                    "peak": 0.32,         # Peak rate (4:00–9:00 p.m.) [MEDIUM confidence]
                    "partPeak": 0.30,     # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                    "offPeak": 0.28,      # Off-Peak rate (all other hours)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,
                },
                "weekends": { # same as weekdays
                    "peak": 0.32,         # Peak rate (4:00–9:00 p.m.) [MEDIUM confidence]
                    "partPeak": 0.30,     # Partial-Peak rate (3:00–4:00 p.m. and 9:00–12:00 a.m.)
                    "offPeak": 0.28,      # Off-Peak rate (all other hours)
                    "peakHours": [16, 17, 18, 19, 20],
                    "partPeakHours": [15, 21, 22, 23],
                    "offPeakHours": [h for h in range(24) if h not in [15, 16, 17, 18, 19, 20, 21, 22, 23]],
                    "fixedCharge": 0.79343,
                },
            }
        },
    }

SCE_RATE_PLANS = {
    "TOU-D-4-9PM": {
            "summer": { # June - September
                "weekdays": {
                    "peak": 0.58,
                    "offPeak": 0.34,
                    "peakHours": list(range(16, 21)),  # 4:00 pm to 9:00 pm
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.70,         # Daily basic charge
                },
                "weekends": {
                    "peak": 0.46,
                    "offPeak": 0.34,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.70,         # Daily basic charge
                },
                "weekdaysAfterBaselineCredit": {
                    "peak": 0.48,
                    "offPeak": 0.24,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.70,         # Daily basic charge
                },
                "weekendAfterBaselineCredit": {
                    "peak": 0.36,
                    "offPeak": 0.24,
                    "peakHours": list(range(16, 21)),
                    "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                    "fixedCharge": 0.70,         # Daily basic charge
                },
            },
            "winter": { # October - May
                "weekdays": {
                    "peak": 0.51,
                    "offPeak": 0.37,
                    "superOffPeak": 0.33,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.70,         # Daily basic charge
                },
                "weekends": { # Same as weekdays in the winter
                    "peak": 0.51,
                    "offPeak": 0.37,
                    "superOffPeak": 0.33,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.70,         # Daily basic charge
                },
                "weekdaysAfterBaselineCredit": {
                    "peak": 0.41,
                    "offPeak": 0.27,
                    "superOffPeak": 0.23,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.70,         # Daily basic charge
                },
                "weekendsAfterBaselineCredit": { # Same as weekdaysAfterBaselineCredit in the winter
                    "peak": 0.41,
                    "offPeak": 0.27,
                    "superOffPeak": 0.23,
                    "peakHours": [16, 17, 18, 19, 20], # Evening
                    "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                    "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                    "fixedCharge": 0.70,         # Daily basic charge
                }
            },
            "fixedCharge": 0.70,         # Daily basic charge
            "minimumDailyCharge": 0.35,  # Minimum daily charge
            "baseline_credit": 0.09,
        },
    "TOU-D-5-8PM": { # https://www.sce.com/residential/rates/Time-Of-Use-Residential-Rate-Plans
        # From website: "Better for customers who end the night early. May benefit those who are home during the day and tend to live in smaller rented dwellings."
        "summer": { # June - September
            "weekdays": {
                "peak": 0.74,      # Highest rate during peak period
                "offPeak": 0.34,   # Off-peak rate
                "peakHours": list(range(17, 20)),  # 5:00–8:00 p.m.
                "offPeakHours": [h for h in range(24) if h not in range(17, 20)],
                "fixedCharge": 0.79,
            },
            "weekends": {
                "peak": 0.54,
                "offPeak": 0.34,
                "peakHours": list(range(17, 20)),
                "offPeakHours": [h for h in range(24) if h not in range(17, 20)],
                "fixedCharge": 0.79,
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.64,
                "offPeak": 0.24,
                "peakHours": [17, 18, 19],  # 5:00–8:00 p.m.
                "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                "fixedCharge": 0.79,
            },
            "weekendAfterBaselineCredit": {
                "peak": 0.44,
                "offPeak": 0.24,
                "peakHours": [17, 18, 19],
                "offPeakHours": [h for h in range(24) if h not in [17, 18, 19]],
                "fixedCharge": 0.79,
            },
        },
        "winter": { # October - May
            "weekdays": {
                "midPeak": 0.60,         # Applies from 5:00 p.m. to 8:00 p.m.
                "offPeak": 0.38,         # Applies during hours outside mid‑peak
                "superOffPeak": 0.32,    # Lowest rate during qualifying conditions
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.79,
            },
            "weekends": {
                "midPeak": 0.60,         # Applies from 5:00 p.m. to 8:00 p.m.
                "offPeak": 0.38,         # Applies during hours outside mid‑peak
                "superOffPeak": 0.32,    # Lowest rate during qualifying conditions
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.79,
            },
            "weekdaysAfterBaselineCredit": {
                "midPeak": 0.50,
                "offPeak": 0.28,
                "superOffPeak": 0.22,
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.79,
            },
            "weekendAfterBaselineCredit": {
                "midPeak": 0.50,
                "offPeak": 0.28,
                "superOffPeak": 0.22,
                "offPeakHours": list(range(0, 8)) + list(range(17, 24)),
                "midPeakHours": list(range(17, 20)),
                "superOffPeakHours": list(range(8, 17)),
                "fixedCharge": 0.79,
            },
        },
        "minimumDailyCharge": 0.35,
        "baseline_credit": 0.09,
    },
    "TOU-D-PRIME": {
        "summer": {
            "weekdays": {
                "peak": 0.59,
                "offPeak": 0.26,
                "peakHours": list(range(16, 21)),  # 4:00 pm to 9:00 pm
                "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                "fixedCharge": 0.79, # Aka Daily Basic Charge
            },
            "weekends": {
                "peak": 0.40,
                "offPeak": 0.26,
                "peakHours": list(range(16, 21)),
                "offPeakHours": [h for h in range(24) if h not in range(16, 21)],
                "fixedCharge": 0.79, # Aka Daily Basic Charge
            }
        },
        "winter": {
            "weekdays": {
                "peak": 0.56,
                "offPeak": 0.24,
                "superOffPeak": 0.24, # Same as offpeak
                "peakHours": [16, 17, 18, 19, 20], # Evening
                "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                "fixedCharge": 0.79, # Aka Daily Basic Charge
            },
            "weekends": { # same as weekdays
                "peak": 0.56,
                "offPeak": 0.24,
                "superOffPeak": 0.24, # Same as offpeak
                "peakHours": [16, 17, 18, 19, 20], # Evening
                "offPeakHours": [21, 22, 23, 24, 1, 2, 3, 4, 5, 6, 7], # Night time
                "superOffPeakHours": [8, 9, 10, 11, 12, 13, 14, 15], # Sunshine hours
                "fixedCharge": 0.79, # Aka Daily Basic Charge
            }
        },
        "minimumDailyCharge": 0,
        "baseline_credit": 0,
    }
}

SDGE_RATE_PLANS = {
    # Updated 2026-07-07 from SDG&E's official Schedule TOU-DR1 Total Rates
    # Table, effective 1/1/2026: https://www.sdge.com/sites/default/files/regulatory/1-1-26%20Schedule%20TOU-DR1%20Total%20Rates%20Table.pdf
    # Previous values were sourced from a consumer-facing marketing page, not
    # the tariff, and were also identical for summer and winter — the real
    # tariff has a meaningfully different (lower) winter rate.
    # "peak"/"offPeak"/"superOffPeak" below is the tariff's below-130%-baseline
    # rate; "...AfterBaselineCredit" is the above-baseline rate. Note: as of
    # this edit, nothing in the pipeline actually reads the
    # "AfterBaselineCredit" tier (no usage-vs-baseline check exists for SDG&E,
    # unlike PG&E's E-TOU-C) — every kWh is billed at the below-baseline rate
    # regardless of usage. Kept both tiers here, correct and documented, but
    # this is a separate, real modeling simplification worth flagging, not
    # something this rate update fixes.
    "TOU-DR1": {
        "summer": {
            "weekdays": {
                "peak": 0.587, # SDGE Also has a CCA customer plan, but I don't model this because SDGE only has partial information (SDGE delivery charges only). "CCA customers must also pay for electric generation at prices determined by the CCA. For CCA electric generation prices, please contact your CCA."
                "offPeak": 0.367,
                "superOffPeak": 0.279,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekends": {
                "peak": 0.587, # prices same as weekday, hours are different
                "offPeak": 0.367,
                "superOffPeak": 0.279,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [14, 15, 21, 22, 23],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.697,
                "offPeak": 0.476,
                "superOffPeak": 0.388,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13], # Same hours as below baseline credit
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekendsAfterBaselineCredit": {
                "peak": 0.697,
                "offPeak": 0.476,
                "superOffPeak": 0.388,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [14, 15, 21, 22, 23],
            },
        },
        "winter": { # No longer identical to summer as of the 1/1/2026 tariff. There are exceptions for March and April but hard to implement
            "weekdays": {
                "peak": 0.513, # SDGE Also has a CCA customer plan, but I don't model this because SDGE only has partial information (SDGE delivery charges only). "CCA customers must also pay for electric generation at prices determined by the CCA. For CCA electric generation prices, please contact your CCA."
                "offPeak": 0.431,
                "superOffPeak": 0.340,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekends": {
                "peak": 0.513, # prices same as weekday, hours are different
                "offPeak": 0.431,
                "superOffPeak": 0.340,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13],
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [14, 15, 21, 22, 23],
            },
            "weekdaysAfterBaselineCredit": {
                "peak": 0.622,
                "offPeak": 0.540,
                "superOffPeak": 0.449,
                "superOffPeakHours": [24, 1, 2, 3, 4, 5, 10, 11, 12, 13], # Same hours as below baseline credit
                "peakHours": [16, 17, 18, 19, 20],
                "offPeakHours": [6, 7, 8, 9, 14, 15],
            },
            "weekendsAfterBaselineCredit": {
                "peak": 0.622,
                "offPeak": 0.540,
                "superOffPeak": 0.449,
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