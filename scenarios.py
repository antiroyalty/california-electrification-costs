"""Centralized scenario definitions for residential electrification cost modeling."""

SCENARIOS = {
    "baseline": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc"}},
    "heat_pump": {"gas": {"hot_water", "cooking"}, "electric": {"appliances", "misc", "heating"}},
    "induction_stove": {"gas": {"hot_water", "heating"}, "electric": {"appliances", "misc", "cooking"}},
    "heat_pump_and_induction_stove": {"gas": {"hot_water"}, "electric": {"appliances", "misc", "cooking", "heating"}},
    "water_heating": {"gas": {"cooking", "heating"}, "electric": {"hot_water", "appliances", "misc"}},
    "heat_pump_and_induction_stove_and_water_heating": {"gas": set(), "electric": {"hot_water", "cooking", "heating", "appliances", "misc"}},
    "baseline_ice_car": {"gas": {"heating", "hot_water", "cooking", "vehicle_fuel"}, "electric": {"appliances", "misc"}},
    "baseline_ev_car": {"gas": {"heating", "hot_water", "cooking"}, "electric": {"appliances", "misc", "vehicle_charging"}},
    "full_electric_ev": {"gas": set(), "electric": {"hot_water", "cooking", "heating", "appliances", "misc", "vehicle_charging"}},
}