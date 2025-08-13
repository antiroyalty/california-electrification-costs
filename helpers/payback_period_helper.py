CAPITAL_COSTS_NEW = {
    "solar": {
        "panel": {
            "base": {                       # the headline cost
                "value": 2.8,
                "unit": "$/W"
            },
            "markup": {
                "installation_labor": {
                    "value": 0, # Usually considered 7.0%, but this is included in the headline cost,
                    "unit": "%"
                },
                "design_engineering": {
                    "value": 0, # Usually considered 28.%, but this is included in the headline cost too.,
                    "unit": "%"
                }
            },
            "sources": [
                "https://pge.wattplan.com/PV/Wizard/?sector=residential", # Back-calculated from PG&E's cost estimator website
                "https://www.energysage.com/local-data/solar-panel-cost/ca/",
                "https://www.tesla.com/learn/solar-panel-cost-breakdown"
            ],
            "last_verified": "2025-06-24"
        }
    },

    "storage": {
        "tesla_powerwall_3": {
            "capacity_kwh": 13.5,           # non-monetary attribute lives here too
            "base": {
                "value": 16_853,
                "unit": "$"
            },
            "sources": [
                "https://www.tesla.com/powerwall/design/overview"
            ],
            "notes": "Cost before incentives; MSRP.",
            "last_verified": "2025-02-15"
        }
    },

    "heat_pump": {
        "average_residential": {
            "base": {
                "value": 19_000,
                "unit": "$"
            },
            "sources": [
                "https://www.rewiringamerica.org/research/home-electrification-cost-estimates",
                "https://www.ethree.com/wp-content/uploads/2023/12/E3_Benefit-Cost-Analysis-of-Targeted-Electrification-and-Gas-Decommissioning-in-California.pdf"
            ],
            "last_verified": "2025-06-01"
        }
    },

    "induction_stove": {
        "average_residential": {
            "base": {
                "value": 2_000,
                "unit": "$"
            },
            "sources": [
                "https://guide.pge.com/browse/induction",
                "https://www.sce.com/factsheet/InductionCookingFactSheet"
            ],
            "last_verified": "2025-06-24"
        }
    },

    "water_heater": {
        "electric_55gal": {
            "base": {
                "value": 2_637,
                "unit": "$"
            },
            "sources": [],
            "last_verified": "2025-06-24"
        }
    }
}

CAPITAL_COSTS = {
    "solar": {
        # Back-calculated from PG&E's cost estimator website: https://pge.wattplan.com/PV/Wizard/?sector=residential&
        # https://www.energysage.com/local-data/solar-panel-cost/ca/
        "dollars_per_watt": 2.8,          # $/W for panels https://www.tesla.com/learn/solar-panel-cost-breakdown
        "installation_labor": 0,         # 7% extra cost for labor
        "design_eng_overhead_percent": 0 # 28% extra cost for design/engineering
    },
    "storage": {
        # Other papers suggest: 1200–$1600 per kilowatt-hour which would = $16320 - $21600 https://www.mdpi.com/2071-1050/16/23/10320#:~:text=residential%20solar%20and%20BESS%2C%20the,6%2FWh%20in%20Texas%20%28Figure%203d
        # https://energylibrary.tesla.com/docs/Public/EnergyStorage/Powerwall/3/Datasheet/en-us/Powerwall-3-Datasheet.pdf
        # https://www.solarreviews.com/blog/is-the-tesla-powerwall-the-best-solar-battery-available
        # https://www.selfgenca.com/home/program_metrics/
        "powerwall_13.5kwh": 16853          # $16853 Cost for one Tesla Powerwall 3 before incentives. https://www.tesla.com/powerwall/design/overview
    },
    "heat_pump": {
        # Rewiring america: $19,000 https://www.rewiringamerica.org/research/home-electrification-cost-estimates
        # "average": 19000, # https://www.nrel.gov/docs/fy24osti/84775.pdf#:~:text=dwelling%20units,9%2C000%2C%20%2420%2C000%2C%20and%20%2424%2C000%20for
        # https://incentives.switchison.org/residents/incentives?state=CA&field_zipcode=90001&_gl=1*1ck7fcj*_gcl_au*OTAxNTQyNjA3LjE3NDQ1NjYxNzg.*_ga*MTEwMTk5ODQ0LjE3NDQ1NjYxNzg.*_ga_8NM1W0PLNN*MTc0NDU2NjE3OC4xLjEuMTc0NDU2NjIwNC4zNC4wLjA.
        # E3 cites single family residential heat pump cost to be $19,000 https://www.ethree.com/wp-content/uploads/2023/12/E3_Benefit-Cost-Analysis-of-Targeted-Electrification-and-Gas-Decommissioning-in-California.pdf#:~:text=%2419k%20%2415k%20%24154k%20The%20significant,commercial%20customers%20and%20therefore%20see
        "average": 19000,
    },
    "induction_stove": {
        # PG&E appliance guide also says $2000 https://guide.pge.com/browse/induction
        "average": 2000 # https://www.sce.com/factsheet/InductionCookingFactSheet
    },
    "water_heater": {
        "average": 2637, # for 55 gal capacity header
    }
}

INCENTIVES = {
    "federal_tax_credit_2023_2032": 0.3, # 30% credit https://www.irs.gov/credits-deductions/residential-clean-energy-credit
    # Federal tax incentives will decline in later years
    "federal_tax_credit_2033": 0.26,
    "federal_tax_credit_2034": 0.22,
    "federal_tax_credit_2035": 0,
    "PGE_SCE_SDGE_General_SGIP_Rebate": 2025, #  General Market SGIP rebate of
        # approximately $150/kilowatt-hour https://www.cpuc.ca.gov/-/media/cpuc-website/files/uploadedfiles/cpucwebsite/content/news_room/newsupdates/2020/sgip-residential-web-120420.pdf
    "storage": {
        # "PG&E": {
            # "storage_rebate": 7500, # Only for homes in wildfire-prone areas, as deemed by PG&E https://www.tesla.com/support/incentives#california-local-incentives
        # },
        # "SCE": {

        # },
        # "SDG&E": {
        #     # https://www.sdge.com/solar/considering-solar
        # }
    },
    "heat_pump": {
        "other_rebates": 0, # 9500, # 9500, # 15200, # 10000, # needed to make it worthwhile
        "max_federal_annual_tax_rebate": 2000, # 2000,
        "california_TECH_incentive": 1500, #1500, # https://incentives.switchison.org/rebate-profile/tech-clean-california-single-family-hvac
    },
    "induction_stove": {
        "max_federal_annual_tax_rebate": 420, # 420, # 1000, # 420, # https://www.geappliances.com/inflation-reduction-act
    },
    "water_heater": {
        "max_federal_annual_tax_rebate": 2000,
        "45-55gal": 700, # $700 rebate
        # "55-75gal": 900 # $900 rebate https://incentives.switchison.org/residents/incentives?state=CA&field_zipcode=90001&_gl=1*1ck7fcj*_gcl_au*OTAxNTQyNjA3LjE3NDQ1NjYxNzg.*_ga*MTEwMTk5ODQ0LjE3NDQ1NjYxNzg.*_ga_8NM1W0PLNN*MTc0NDU2NjE3OC4xLjEuMTc0NDU2NjIwNC4zNC4wLjA.
    },
}