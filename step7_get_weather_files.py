import os
import requests
import pandas as pd
from geopy.geocoders import Nominatim
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("NREL_WEATHER_API_KEY", "mock_api_key")

def process(base_input_dir, output_dir, scenarios, housing_types, counties=None):
    # Initialize geolocator for dynamic centroid fetching
    geolocator = Nominatim(user_agent="county_centroid_fetcher")

    for scenario in scenarios:
        for housing_type in housing_types:
            # Define scenario path
            scenario_path = os.path.join(base_input_dir, scenario, housing_type)
            if not os.path.exists(scenario_path):
                print(f"Scenario path not found: {scenario_path}")
                continue

            if counties == None:
                # Dynamically retrieve counties
                counties = [county for county in os.listdir(scenario_path)
                            if os.path.isdir(os.path.join(scenario_path, county))]

            for county in counties:
                print(f"Processing {county}...")

                try:
                    # Get centroid coordinates dynamically using geopy
                    location = geolocator.geocode(f"{county}, California")
                    if location is None:
                        print(f"Could not find centroid for {county}. Skipping...")
                        continue
                    latitude, longitude = location.latitude, location.longitude

                    # Fetch TMY data from NREL
                    base_url = "https://developer.nrel.gov/api/solar/nsrdb_psm3_download.csv"
                    params = {
                        "api_key": API_KEY,
                        "wkt": f"POINT({longitude} {latitude})",
                        "names": "tmy",  # Requesting Typical Meteorological Year data
                        "interval": "60",  # Hourly data
                        "utc": "true",
                        "email": "ana.santasheva@berkeley.edu" # TODO Ana: REDACT
                    }

                    print(f"Fetching TMY data for {county} ({latitude}, {longitude})...")

                    response = requests.get(base_url, params=params)

                    if response.status_code == 200:
                        file_path = os.path.join(output_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv")
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        with open(file_path, "w") as file:
                            file.write(response.text)
                        print(f"Saved TMY data for {county} to {file_path}")
                    else:
                        print(f"Failed to fetch TMY data for {county}: {response.status_code} {response.text}")
                except Exception as e:
                    print(f"Error processing {county}: {e}")