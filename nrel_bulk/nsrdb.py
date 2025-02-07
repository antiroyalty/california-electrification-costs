import os
import requests
import time
import pandas as pd
from geopy.geocoders import Nominatim
from dotenv import load_dotenv

# Load API key from environment variables
load_dotenv()
API_KEY = os.getenv("NREL_WEATHER_API_KEY", "mock_api_key")

# Base URL for NSRDB API
BASE_URL = "https://developer.nrel.gov/api/solar/psm3-5min-download.json"

# Output directory
OUTPUT_DIR = "nsrdb_california_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load California locations dataset (Ensure this file has 'city' and 'county' columns)
CALIFORNIA_LOCATIONS_FILE = "california_locations.csv"

def get_california_locations():
    """Load a list of California locations with city and county names."""
    df = pd.read_csv(CALIFORNIA_LOCATIONS_FILE)
    return df[["city", "county"]].values.tolist()  # Returns list of (city, county) pairs

def download_nsrdb_data(params, output_filename):
    """Fetch NSRDB data for a specific location and save it."""
    print(f"📡 Requesting data for {params['wkt']}...")
    
    response = requests.post(BASE_URL, data=params)

    if response.status_code == 200:
        result = response.json()
        
        if "outputs" in result and "downloadUrls" in result["outputs"]:
            csv_url = result["outputs"]["downloadUrls"]["csv"]
            csv_response = requests.get(csv_url)

            if csv_response.status_code == 200:
                output_path = os.path.join(OUTPUT_DIR, output_filename)
                with open(output_path, "wb") as file:
                    file.write(csv_response.content)
                print(f"✅ Data saved to {output_path}")
            else:
                print(f"❌ Failed to download CSV: {csv_response.status_code}")
        else:
            print(f"❌ Unexpected API response format: {result}")
    else:
        print(f"❌ API request failed: {response.status_code} - {response.text}")

def process_california_locations():
    """Iterate through all California locations and fetch NSRDB data."""
    
    geolocator = Nominatim(user_agent="ca_nsrdb_fetcher", timeout=10)
    locations = get_california_locations()

    for i, (city, county) in enumerate(locations):
        try:
            print(f"🌍 Processing {city}, {county} County...")
            
            # Get latitude & longitude using geopy
            location = geolocator.geocode(f"{city}, {county}, California, USA")
            if location is None:
                print(f"❌ Could not find coordinates for {city}, {county}. Skipping...")
                continue

            latitude, longitude = location.latitude, location.longitude

            # Prepare API request parameters
            params = {
                "api_key": API_KEY,
                "names": "tmy",  # Typical Meteorological Year
                "leap_day": "false",
                "interval": "60",
                "utc": "true",
                "full_name": "Your Name",
                "email": "your.email@example.com",
                "affiliation": "Your Organization",
                "mailing_list": "false",
                "reason": "Research",
                "attributes": "dhi,dni,wind_speed_10m_nwp,surface_air_temperature_nwp",
                "wkt": f"POINT({longitude} {latitude})",
            }

            # Create organized file structure
            output_filename = f"{county}_{city}_weather_TMY.csv".replace(" ", "_")
            output_path = os.path.join(OUTPUT_DIR, county, output_filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Fetch and save data
            download_nsrdb_data(params, output_filename)

        except Exception as e:
            print(f"⚠️ Error processing {city}, {county}: {e}")

        # Enforce API rate limits (1 request every 2 seconds)
        if i < len(locations) - 1:
            print("⏳ Waiting 2 seconds before next request...")
            time.sleep(2)

# Run the process for all California locations
process_california_locations()