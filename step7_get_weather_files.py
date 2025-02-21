import os
import requests
import pandas as pd
from geopy.geocoders import Nominatim
from dotenv import load_dotenv

from helpers import slugify_county_name, get_counties, get_scenario_path, log, norcal_counties, central_counties, socal_counties

load_dotenv()
API_KEY = os.getenv("NREL_WEATHER_API_KEY", "mock_api_key")

def process(base_input_dir, output_dir, scenarios, housing_types, counties=None):
    # Initialize geolocator for dynamic centroid fetching
    geolocator = Nominatim(user_agent="county_centroid_fetcher")

    for scenario in scenarios:
        for housing_type in housing_types:
            scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
            counties = get_counties(scenario_path, counties)

            for county in counties:
                county = slugify_county_name(county)
                file_path = os.path.join(output_dir, scenario, housing_type, county, f"weather_TMY_{county}.csv")
                
                if os.path.exists(file_path):
                    log(
                        at="process",
                        county=county,
                        new_files_downloaded="F",
                        files_at=file_path,
                    )
                    continue

                try:
                    # Get centroid coordinates dynamically using geopy
                    location = geolocator.geocode(f"{county}, California")
                    if location is None:
                        log(
                            at="process",
                            county=county,
                            files_downloaded="F",
                            description="could not find centroid"
                        )
                        continue
                    latitude, longitude = location.latitude, location.longitude

                    # Fetch TMY data from NREL
                    base_url = "https://developer.nrel.gov/api/solar/nsrdb_psm3_download.csv"
                    params = {
                        "api_key": API_KEY,
                        "wkt": f"POINT({longitude} {latitude})",
                        "names": "tmy",  # Requesting Typical Meteorological Year data
                        # TODO: Ana, adjust this to be AMY + 2018 if I can
                        "interval": "60",  # Hourly data
                        "utc": "true",
                        "email": "ana.santasheva@berkeley.edu"  # TODO Ana: REDACT
                    }

                    print(f"Fetching TMY data for {county} ({latitude}, {longitude})...")

                    response = requests.get(base_url, params=params)

                    if response.status_code == 200:
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        with open(file_path, "w") as file:
                            file.write(response.text)
                        print(f"Saved TMY data for {county} to {file_path}")
                    else:
                        print(f"Failed to fetch TMY data for {county}: {response.status_code} {response.text}")

                    log(
                        at="process",
                        title="get weather files",
                        county=county,
                        files_downloaded="T",
                        latitude=latitude,
                        longitude=longitude,
                        response_code=response.status_code,
                        resopnse_text=response.text,
                        saved_to=file_path,
                    )
                
                except Exception as e:
                    print(f"Error processing {county}: {e}")

# Done: single-family-detached: norcal_counties, socal_counties, central_counties
# process("data", "data/loadprofiles", "baseline", ["single-family-detached"], norcal_counties)