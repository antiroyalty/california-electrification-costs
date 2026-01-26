import os
import pandas as pd

from helpers.main_helpers import slugify_county_name, get_counties, get_scenario_path, log

# Which columns should be used to calculate electricity and gas rates based on each scenario
SCENARIO_DATA_MAP = {
    "baseline": {
        # baseline
        "default": {
            "electricity": {
                "file_prefix": "electricity_loads_", # or "solar_storage_dispatch_profiles_"
                "column": "total_load" # or + "Total Load"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.building_avg.therms" # TODO: Ana, why am I using avg therms here? Is this a miscalculation? Revisit this logic. This is because this is a COUNTY average, not a time average
            },
        },
        # baseline w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "gas_loads_",
                "column": "load.gas.building_avg.therms"
            }
        },
    },
    # Co-optimized variants for all scenarios — use combined default profiles plus SAM outputs
    "induction_stove_coopt": {
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_induction_stove_coopt_",
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh",
            },
            "gas": {
                "file_prefix": "combined_profiles_induction_stove_coopt_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            },
        },
        "solar_storage": {
            "electricity": {"file_prefix": "solar_storage_dispatch_profiles_", "column": "Grid to Load"},
            "gas": {"file_prefix": "combined_profiles_induction_stove_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
    },
    "water_heating_coopt": {
        "default": {
            "electricity": {"file_prefix": "combined_profiles_water_heating_coopt_", "column": "electricity.real_and_simulated.for_typical_county_home.kwh"},
            "gas": {"file_prefix": "combined_profiles_water_heating_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
        "solar_storage": {
            "electricity": {"file_prefix": "solar_storage_dispatch_profiles_", "column": "Grid to Load"},
            "gas": {"file_prefix": "combined_profiles_water_heating_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
    },
    "heat_pump_coopt": {
        "default": {
            "electricity": {"file_prefix": "combined_profiles_heat_pump_coopt_", "column": "electricity.real_and_simulated.for_typical_county_home.kwh"},
            "gas": {"file_prefix": "combined_profiles_heat_pump_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
        "solar_storage": {
            "electricity": {"file_prefix": "solar_storage_dispatch_profiles_", "column": "Grid to Load"},
            "gas": {"file_prefix": "combined_profiles_heat_pump_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
    },
    "heat_pump_and_induction_stove_and_water_heating_coopt": {
        "default": {
            "electricity": {"file_prefix": "combined_profiles_heat_pump_and_induction_stove_and_water_heating_coopt_", "column": "electricity.real_and_simulated.for_typical_county_home.kwh"},
            "gas": {"file_prefix": "combined_profiles_heat_pump_and_induction_stove_and_water_heating_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
        "solar_storage": {
            "electricity": {"file_prefix": "solar_storage_dispatch_profiles_", "column": "Grid to Load"},
            "gas": {"file_prefix": "combined_profiles_heat_pump_and_induction_stove_and_water_heating_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
    },
    "baseline_ice_car_coopt": {
        "default": {
            "electricity": {"file_prefix": "combined_profiles_baseline_ice_car_coopt_", "column": "electricity.real_and_simulated.for_typical_county_home.kwh"},
            "gas": {"file_prefix": "combined_profiles_baseline_ice_car_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
        "solar_storage": {
            "electricity": {"file_prefix": "solar_storage_dispatch_profiles_", "column": "Grid to Load"},
            "gas": {"file_prefix": "combined_profiles_baseline_ice_car_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
    },
    "baseline_ev_car_coopt": {
        "default": {
            "electricity": {"file_prefix": "combined_profiles_baseline_ev_car_coopt_", "column": "electricity.real_and_simulated.for_typical_county_home.kwh"},
            "gas": {"file_prefix": "combined_profiles_baseline_ev_car_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
        "solar_storage": {
            "electricity": {"file_prefix": "solar_storage_dispatch_profiles_", "column": "Grid to Load"},
            "gas": {"file_prefix": "combined_profiles_baseline_ev_car_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
    },
    "full_electric_ev_coopt": {
        "default": {
            "electricity": {"file_prefix": "combined_profiles_full_electric_ev_coopt_", "column": "electricity.real_and_simulated.for_typical_county_home.kwh"},
            "gas": {"file_prefix": "combined_profiles_full_electric_ev_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
        "solar_storage": {
            "electricity": {"file_prefix": "solar_storage_dispatch_profiles_", "column": "Grid to Load"},
            "gas": {"file_prefix": "combined_profiles_full_electric_ev_coopt_", "column": "gas.hourly_total.for_typical_county_home.therms"},
        },
    },
    # Co-optimized variant (Step 9b output). Uses combined default profiles plus SAM outputs.
    "baseline_coopt": {
        # Baseline (no PV/storage): combined electricity + gas profile per county
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_baseline_coopt_",
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh",
            },
            "gas": {
                "file_prefix": "combined_profiles_baseline_coopt_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            },
        },
        # With PV/storage: electricity from SAM; gas unchanged (same combined file)
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load",
            },
            "gas": {
                "file_prefix": "combined_profiles_baseline_coopt_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            },
        },
    },
    "heat_pump": {
        # household adopted heat pump
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_heat_pump_", # or "solar_storage_dispatch_profiles_"
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh" # or + "Total Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_heat_pump_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        # household adopted heat pump w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_heat_pump_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            }
        }
    },
    "induction_stove": {
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_induction_stove_", # or "solar_storage_dispatch_profiles_"
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh" # or + "Total Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_induction_stove_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_induction_stove_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            }
        }
    },
    "heat_pump_and_induction_stove": {
        # household adopted heat pump
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_heat_pump_and_induction_stove_", # or "solar_storage_dispatch_profiles_"
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh" # or + "Total Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_heat_pump_and_induction_stove_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        # household adopted heat pump w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_heat_pump_and_induction_stove_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            }
        }
    },
    "water_heating": {
        # household adopted water heating
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_water_heating_", # or "solar_storage_dispatch_profiles_"
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh" # or + "Total Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_water_heating_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        # household adopted water heating w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_water_heating_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            }
        }
    },
    "heat_pump_and_induction_stove_and_water_heating": {
        # household adopted water heating
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_heat_pump_and_induction_stove_and_water_heating_", # or "solar_storage_dispatch_profiles_"
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh" # or + "Total Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_heat_pump_and_induction_stove_and_water_heating_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        # household adopted water heating w/ solar + storage
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_heat_pump_and_induction_stove_and_water_heating_",
                "column": "gas.hourly_total.for_typical_county_home.therms",
            }
        }
    },
    "baseline_ice_car": {
        # baseline with ICE car (gasoline consumption tracked separately)
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_baseline_ice_car_",
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh"
            },
            "gas": {
                "file_prefix": "combined_profiles_baseline_ice_car_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_baseline_ice_car_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        }
    },
    "baseline_ev_car": {
        # baseline with EV car (includes vehicle charging in electricity)
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_baseline_ev_car_",
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh"
            },
            "gas": {
                "file_prefix": "combined_profiles_baseline_ev_car_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_baseline_ev_car_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        }
    },
    "full_electric_ev": {
        # fully electric appliances with EV car
        "default": {
            "electricity": {
                "file_prefix": "combined_profiles_full_electric_ev_",
                "column": "electricity.real_and_simulated.for_typical_county_home.kwh"
            },
            "gas": {
                "file_prefix": "combined_profiles_full_electric_ev_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        },
        "solar_storage": {
            "electricity": {
                "file_prefix": "solar_storage_dispatch_profiles_",
                "column": "Grid to Load"
            },
            "gas": {
                "file_prefix": "combined_profiles_full_electric_ev_",
                "column": "gas.hourly_total.for_typical_county_home.therms"
            }
        }
    },
}

OUTPUT_FILE_NAME = "loadprofiles_for_rates"
OUTPUT_COLUMNS = [
    "timestamp",
    "default.electricity.kwh",
    "default.gas.therms",
    # Retail (no feedback to grid)
    "retail.imports.kwh",
    "retail.exports.kwh",
    # NEM3 (imports on plan, ACC credits for exports)
    "nem3.imports.kwh",
    "nem3.exports.kwh",
    # Gas (unchanged by PV/storage)
    "solarstorage.gas.therms",
]

def aggregate_to_hourly(file_path, column_name):
    try:
        df = pd.read_csv(file_path, parse_dates=["timestamp"])
        if column_name not in df.columns:
            raise ValueError(f"Column '{column_name}' not found in file: {file_path}")
        
        df = df.set_index("timestamp")
        hourly_df = df.resample("H")[column_name].sum().reset_index() # Resample and reindex

        return hourly_df[column_name] # Return the single column of interest
    except Exception as e:
        raise RuntimeError(f"Error processing file {file_path}: {e}")

def get_file_path(path, county, file_prefix):
    return os.path.join(path, county, f"{file_prefix}{county}.csv")

def read_load_profile(file_path, column_name):
    try:
        df = pd.read_csv(file_path, usecols=[column_name])
        return df[column_name]
    except Exception as e:
        raise RuntimeError(f"Error reading file {file_path}: {e}")

## Optional-profile reading has been removed on purpose to ensure failures surface early.

def _read_step9_imports(series_path: str) -> pd.Series:
    """Read hourly imports from Step 9 base CSV. Imports = Grid to Load + (Grid to Battery if present)."""
    df = pd.read_csv(series_path)
    if "Grid to Load" not in df.columns:
        raise RuntimeError(f"Column 'Grid to Load' not found in file: {series_path}")
    imports = df["Grid to Load"].astype(float)
    if "Grid to Battery" in df.columns:
        imports = imports + df["Grid to Battery"].astype(float)
    return imports


def _read_step9_exports(base_path: str, exports_path: str) -> pd.Series:
    """Read hourly exports strictly from the exports-only CSV.

    Required: 'Exports to Grid (kWh)' present in solar_storage_dispatch_profiles_with_exports_ file.
    No fallback is used to avoid silent misinterpretation of results.
    """
    if not os.path.exists(exports_path):
        raise RuntimeError(
            f"Exports file not found: {exports_path}. Ensure Step 9/9b wrote 'solar_storage_dispatch_profiles_with_exports_<county>.csv'"
        )
    df_exp = pd.read_csv(exports_path)
    if "Exports to Grid (kWh)" not in df_exp.columns:
        raise RuntimeError(
            f"Column 'Exports to Grid (kWh)' not found in file: {exports_path}"
        )
    return df_exp["Exports to Grid (kWh)"].astype(float)


def prepare_for_rates_analysis(base_input_dir, base_output_dir, housing_type, scenario, county):
    directory = SCENARIO_DATA_MAP.get(scenario, {})
    county = slugify_county_name(county)
    path = get_scenario_path(base_input_dir, scenario, housing_type)

    log(at="step9", county=county, path=path)

    electricity_default_file = get_file_path(path, county, directory["default"]["electricity"]["file_prefix"])
    gas_default_file = get_file_path(path, county, directory["default"]["gas"]["file_prefix"])
    # Step 9 base and exports files
    step9_base_electric_file = get_file_path(path, county, directory["solar_storage"]["electricity"]["file_prefix"])  # solar_storage_dispatch_profiles_
    step9_exports_electric_file = get_file_path(
        path,
        county,
        directory["solar_storage"]["electricity"]["file_prefix"].replace("solar_storage_dispatch_profiles_", "solar_storage_dispatch_profiles_with_exports_")
    )
    gas_solar_storage_file = get_file_path(path, county, directory["solar_storage"]["gas"]["file_prefix"])

    timestamp = read_load_profile(electricity_default_file, "timestamp")
    electricity_default = read_load_profile(
        electricity_default_file, directory["default"]["electricity"]["column"]
    ).astype(float)
    # Imports for both Retail and NEM3 (identical imports)
    retail_imports = _read_step9_imports(step9_base_electric_file)
    nem3_imports = retail_imports.copy()
    gas_default_hourly = aggregate_to_hourly(gas_default_file, directory["default"]["gas"]["column"])
    gas_solar_storage_hourly = aggregate_to_hourly(gas_solar_storage_file, directory["solar_storage"]["gas"]["column"])

    # NEM3 exports: strict — require the exports‑only CSV
    nem3_exports = _read_step9_exports(step9_base_electric_file, step9_exports_electric_file)

    # Sanity check: enforce aligned lengths for all series
    expected_len = len(timestamp)
    series_map = {
        "default.electricity.kwh": electricity_default,
        "retail.imports.kwh": retail_imports,
        "nem3.imports.kwh": nem3_imports,
        "nem3.exports.kwh": nem3_exports,
        "default.gas.therms": gas_default_hourly,
        "solarstorage.gas.therms": gas_solar_storage_hourly,
    }
    for name, s in series_map.items():
        if len(s) != expected_len:
            raise RuntimeError(
                f"Length mismatch for {name}: expected {expected_len}, got {len(s)}"
            )

    # Retail exports are zero (no feedback to grid), aligned to expected length
    retail_exports = pd.Series([0.0] * expected_len)

    combined_df = pd.DataFrame(
        {
            "timestamp": timestamp,
            "default.electricity.kwh": electricity_default,
            "default.gas.therms": gas_default_hourly,
            # Retail view (no feedback to grid)
            "retail.imports.kwh": retail_imports,
            "retail.exports.kwh": retail_exports,
            # NEM3 view (imports − ACC credits)
            "nem3.imports.kwh": nem3_imports,
            "nem3.exports.kwh": nem3_exports,
            # Gas (unchanged by PV/storage)
            "solarstorage.gas.therms": gas_solar_storage_hourly,
        }
    )

    output_file_path = os.path.join(base_output_dir, scenario, housing_type, county, f"{OUTPUT_FILE_NAME}_{county}.csv")
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
    combined_df.to_csv(output_file_path, index=False)
    
    log(at="step10_aggregator", saved_to=output_file_path)

def process(base_input_dir, base_output_dir, scenario, housing_types, counties=None):
    for housing_type in housing_types:
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        counties_list = get_counties(scenario_path, counties)
        for county in counties_list:
            prepare_for_rates_analysis(base_input_dir, base_output_dir, housing_type, scenario, county)

if __name__ == '__main__':
    from helpers.main_helpers import norcal_counties, central_counties, socal_counties
    
    # Configuration
    scenario = "heat_pump"
    housing_types = ["single-family-detached"]
    
    process(
        base_input_dir="data/loadprofiles",
        base_output_dir="data/loadprofiles", 
        scenario=scenario,
        housing_types=housing_types,
        counties=norcal_counties + central_counties + socal_counties
    )
