LIFETIMES_DEFAULT = {
    "solar": 25,
    "storage": 15,
    "heat_pump": 15,
    "induction_stove": 15,
    "water_heater": 15,
}

THERM_TO_KWH = 29.3001

# Real discount rate used to annualize capex throughout the pipeline (CRF, NPV,
# LCOE). Defined once here so a rate change or sensitivity sweep is a single
# edit instead of a repo-wide find-and-replace across ~25 default arguments.
DEFAULT_DISCOUNT_RATE = 0.07

