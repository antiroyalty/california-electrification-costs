import os
import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta
from my_module import aggregate_columns, combine_profiles, process, OUTPUT_FILE_PREFIX, SCENARIO_DATA_MAP

@pytest.fixture
def create_csv(tmp_path):
    def _create_csv(data, filename):
        file_path = tmp_path / filename
        pd.DataFrame(data).to_csv(file_path, index=False)
        return str(file_path)
    return _create_csv

@pytest.fixture
def setup_input_structure(tmp_path):
    def _setup(scenario, housing_type, county, data):
        county_slug = county.lower().replace(" ", "_")
        base_path = tmp_path / "input" / "baseline" / housing_type / county_slug
        base_path.mkdir(parents=True, exist_ok=True)
        files = {
            "electricity": f"electricity_loads_{county_slug}.csv",
            "gas": f"gas_loads_{county_slug}.csv",
            "electricity_simulated": f"electricity_loads_simulated_{county_slug}.csv"
        }
        for key, file_name in files.items():
            if key in data:
                pd.DataFrame(data[key]).to_csv(base_path / file_name, index=False)
        return str(tmp_path / "input")
    return _setup

@pytest.fixture
def setup_input_structure_process(tmp_path):
    def _setup(scenario, housing_type, county, data):
        county_slug = county.lower().replace(" ", "_")
        base_path = tmp_path / scenario / housing_type / county_slug
        base_path.mkdir(parents=True, exist_ok=True)
        files = {
            "electricity": f"electricity_loads_{county_slug}.csv",
            "gas": f"gas_loads_{county_slug}.csv",
            "electricity_simulated": f"electricity_loads_simulated_{county_slug}.csv"
        }
        for key, file_name in files.items():
            if key in data:
                pd.DataFrame(data[key]).to_csv(base_path / file_name, index=False)
        return str(tmp_path)
    return _setup

class TestAggregateColumns:
    def test_sum_no_resample(self, tmp_path):
        timestamps = [datetime(2020, 1, 1, h) for h in range(3)]
        data = {"timestamp": timestamps, "col": [1, 2, 3]}
        file_path = tmp_path / "test.csv"
        pd.DataFrame(data).to_csv(file_path, index=False)
        result = aggregate_columns(str(file_path), ["col"], operation="sum", resample_to_hourly=False)
        expected = pd.Series([1, 2, 3], index=pd.to_datetime(timestamps))
        pd.testing.assert_series_equal(result, expected)

    def test_subtract_no_resample(self, tmp_path):
        timestamps = [datetime(2020, 1, 1, h) for h in range(3)]
        data = {"timestamp": timestamps, "col": [1, 2, 3]}
        file_path = tmp_path / "test.csv"
        pd.DataFrame(data).to_csv(file_path, index=False)
        result = aggregate_columns(str(file_path), ["col"], operation="subtract", resample_to_hourly=False)
        expected = pd.Series([-1, -2, -3], index=pd.to_datetime(timestamps))
        pd.testing.assert_series_equal(result, expected)

    def test_resample(self, tmp_path):
        start = datetime(2020, 1, 1, 0)
        timestamps = [start + timedelta(minutes=15 * i) for i in range(4)]
        data = {"timestamp": timestamps, "col": [1, 2, 3, 4]}
        file_path = tmp_path / "test.csv"
        pd.DataFrame(data).to_csv(file_path, index=False)
        result = aggregate_columns(str(file_path), ["col"], operation="sum", resample_to_hourly=True)
        expected_index = pd.date_range(start=start, periods=1, freq="H")
        expected = pd.Series([sum([1, 2, 3, 4])], index=expected_index)
        pd.testing.assert_series_equal(result, expected)

    def test_invalid_operation(self, tmp_path):
        data = {"timestamp": [datetime(2020, 1, 1, 0)], "col": [1]}
        file_path = tmp_path / "test.csv"
        pd.DataFrame(data).to_csv(file_path, index=False)
        with pytest.raises(RuntimeError):
            aggregate_columns(str(file_path), ["col"], operation="invalid", resample_to_hourly=False)

class TestCombineProfiles:
    def test_baseline(self, tmp_path, setup_input_structure):
        scenario = "baseline"
        housing_type = "single-family-detached"
        county = "Alameda County"
        county_slug = county.lower().replace(" ", "_")
        data = {
            "electricity": {"timestamp": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"], "total_load": [10, 20]},
            "gas": {"timestamp": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"], "load.gas.avg.therms": [5, 15]}
        }
        input_dir = setup_input_structure(scenario, housing_type, county, data)
        output_dir = str(tmp_path / "output")
        scenario_data_map = SCENARIO_DATA_MAP[scenario]
        combined_df = combine_profiles(input_dir, output_dir, scenario, housing_type, county, scenario_data_map)
        expected_electricity = np.array([10, 20])
        expected_gas = pd.Series([5, 15], index=pd.to_datetime(["2020-01-01 00:00:00", "2020-01-01 01:00:00"]))
        pd.testing.assert_series_equal(pd.Series(combined_df["electricity.real_and_simulated.for_typical_county_home.kwh"]),
                                       pd.Series(expected_electricity))
        pd.testing.assert_series_equal(pd.Series(combined_df["gas.hourly_total.for_typical_county_home.therms"]),
                                       expected_gas)
        output_file = os.path.join(output_dir, scenario, housing_type, county_slug,
                                   f"{OUTPUT_FILE_PREFIX}_{scenario}_{county_slug}.csv")
        assert os.path.exists(output_file)

    def test_heat_pump(self, tmp_path, setup_input_structure):
        scenario = "heat_pump_and_water_heater"
        housing_type = "single-family-detached"
        county = "Alameda County"
        county_slug = county.lower().replace(" ", "_")
        data = {
            "electricity": {"timestamp": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"], "total_load": [10, 20]},
            "electricity_simulated": {"timestamp": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"],
                                      "simulated.electricity.heat_pump.energy_consumption.electricity.total.kwh": [2, 3],
                                      "simulated.electricity.hot_water.energy_consumption.electricity.total.kwh": [1, 1]},
            "gas": {"timestamp": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"], "load.gas.avg.therms": [5, 15]}
        }
        input_dir = setup_input_structure(scenario, housing_type, county, data)
        output_dir = str(tmp_path / "output")
        scenario_data_map = SCENARIO_DATA_MAP[scenario]
        combined_df = combine_profiles(input_dir, output_dir, scenario, housing_type, county, scenario_data_map)
        expected_electricity = np.array([10 + (2 + 1), 20 + (3 + 1)])
        expected_gas = pd.Series([5, 15], index=pd.to_datetime(["2020-01-01 00:00:00", "2020-01-01 01:00:00"]))
        pd.testing.assert_series_equal(pd.Series(combined_df["electricity.real_and_simulated.for_typical_county_home.kwh"]),
                                       pd.Series(expected_electricity))
        pd.testing.assert_series_equal(pd.Series(combined_df["gas.hourly_total.for_typical_county_home.therms"]),
                                       expected_gas)
        output_file = os.path.join(output_dir, scenario, housing_type, county_slug,
                                   f"{OUTPUT_FILE_PREFIX}_{scenario}_{county_slug}.csv")
        assert os.path.exists(output_file)

class TestProcessIntegration:
    @pytest.fixture
    def setup_process_input(self, tmp_path):
        def _setup(scenario, housing_type, county, data):
            county_slug = county.lower().replace(" ", "_")
            base_path = tmp_path / scenario / housing_type / county_slug
            base_path.mkdir(parents=True, exist_ok=True)
            files = {
                "electricity": f"electricity_loads_{county_slug}.csv",
                "gas": f"gas_loads_{county_slug}.csv",
                "electricity_simulated": f"electricity_loads_simulated_{county_slug}.csv"
            }
            for key, file_name in files.items():
                if key in data:
                    pd.DataFrame(data[key]).to_csv(base_path / file_name, index=False)
            return str(tmp_path)
        return _setup

    def fake_get_scenario_path(self, input_dir, scenario, housing_type):
        return os.path.join(input_dir, scenario, housing_type)

    def fake_get_counties(self, scenario_path, counties):
        return counties

    def test_process(self, tmp_path, setup_process_input, monkeypatch):
        scenario = "baseline"
        housing_type = "single-family-detached"
        county = "Alameda County"
        data = {
            "electricity": {"timestamp": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"], "total_load": [10, 20]},
            "gas": {"timestamp": ["2020-01-01 00:00:00", "2020-01-01 01:00:00"], "load.gas.avg.therms": [5, 15]}
        }
        input_dir = setup_process_input(scenario, housing_type, county, data)
        output_dir = os.path.join(str(tmp_path), "output")
        monkeypatch.setattr("my_module.get_scenario_path", self.fake_get_scenario_path)
        monkeypatch.setattr("my_module.get_counties", self.fake_get_counties)
        results = process(input_dir, output_dir, [scenario], [housing_type], [county])
        assert len(results) == 1
        combined_df = results[0]
        expected_electricity = np.array([10, 20])
        expected_gas = pd.Series([5, 15],
                                 index=pd.to_datetime(["2020-01-01 00:00:00", "2020-01-01 01:00:00"]))
        pd.testing.assert_series_equal(pd.Series(combined_df["electricity.real_and_simulated.for_typical_county_home.kwh"]),
                                       pd.Series(expected_electricity))
        pd.testing.assert_series_equal(pd.Series(combined_df["gas.hourly_total.for_typical_county_home.therms"]),
                                       expected_gas)
        county_slug = county.lower().replace(" ", "_")
        output_file = os.path.join(output_dir, scenario, housing_type, county_slug,
                                   f"{OUTPUT_FILE_PREFIX}_{scenario}_{county_slug}.csv")
        assert os.path.exists(output_file)