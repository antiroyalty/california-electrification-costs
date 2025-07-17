import os
import requests
import pandas as pd
from geopy.geocoders import Nominatim
from dotenv import load_dotenv
from io import StringIO

from helpers import slugify_county_name, get_counties, get_scenario_path, log, norcal_counties, central_counties, socal_counties

FILE_PREFIX = "weather_TMY"
NREL_BASE_URL = "https://developer.nrel.gov/api/solar/nsrdb_psm3_download.csv"
DEFAULT_EMAIL = "ana.santasheva@berkeley.edu"  # TODO: Make configurable via environment variable
REQUEST_INTERVAL = "60"  # Hourly data

load_dotenv()
API_KEY = os.getenv("NREL_WEATHER_API_KEY", "mock_api_key")

def data_only_for_year(year, county, filepath):
    """
    Reads the weather file at 'filepath', retains its header lines, filters the data for
    the specified year, and writes a new CSV file for that year.
    
    The new file will be named: FILE_PREFIX_{county}_{year}.csv in the same directory as 'filepath'.
    """
    # Use the input filepath as the source CSV file.
    input_csv = filepath
    # Create output file path in the same directory as input_csv.
    output_csv = os.path.join(os.path.dirname(filepath), f"{FILE_PREFIX}_{county}_{year}.csv")
    
    # Read all lines so we can retain the header lines.
    with open(input_csv, "r") as f:
        all_lines = f.readlines()

    # Determine header line count.
    # If the first line contains "Year", assume it's the only header line.
    if "Year" in all_lines[0]:
        header_lines = all_lines[:1]
        data_lines = all_lines[1:]
    else:
        header_lines = all_lines[:2]
        data_lines = all_lines[2:]
        
    # Combine data lines into a single string.
    data_str = "".join(data_lines)
    # Since the sample shows comma-separated values, use sep=",".
    df = pd.read_csv(StringIO(data_str), sep=",")
    
    # Clean up column names: remove extra whitespace.
    df.columns = [col.strip() for col in df.columns]

    print("DataFrame head:\n", df.head())
    
    # Find the column that corresponds to 'year' (case-insensitive)
    year_col = None
    for col in df.columns:
        if col.lower() == "year":
            year_col = col
            break
    if year_col is None:
        raise ValueError("The CSV file does not contain a 'Year' column.")
    
    # Filter rows where the 'Year' column matches the target year.
    df_filtered = df[df[year_col] == year]

    # Write the new CSV with the same header structure.
    with open(output_csv, "w") as f_out:
        for header in header_lines:
            f_out.write(header)
        df_filtered.to_csv(f_out, sep=",", index=False)
    
    print(f"Created weather file for {county} {year}: {output_csv}")
    return output_csv

def get_county_coordinates(county_name):
    """Get latitude/longitude for a county using geocoding."""
    geolocator = Nominatim(user_agent="county_centroid_fetcher")
    location = geolocator.geocode(f"{county_name}, California")
    if location is None:
        return None
    return location.latitude, location.longitude

def fetch_weather_data(latitude, longitude, county):
    """Fetch TMY data from NREL API."""
    params = {
        "api_key": API_KEY,
        "wkt": f"POINT({longitude} {latitude})",
        "names": "tmy",  # Requesting Typical Meteorological Year data.
        "interval": REQUEST_INTERVAL,
        "utc": "true",
        "email": DEFAULT_EMAIL
    }

    print(f"Fetching TMY data for {county} ({latitude}, {longitude})...")
    response = requests.get(NREL_BASE_URL, params=params)
    return response

def should_skip_processing(file_path, year_specific_path, force_recompute):
      """Check if processing should be skipped."""
      if force_recompute:
          return False
      return os.path.exists(file_path) and os.path.exists(year_specific_path)

def process_county_weather(county, output_dir, scenario, housing_type, year, force_recompute):
    """Process weather data for a single county."""
    county = slugify_county_name(county)
    file_path = os.path.join(output_dir, scenario, housing_type, county, f"{FILE_PREFIX}_{county}.csv")
    year_specific_path = os.path.join(output_dir, scenario, housing_type, county,
  f"{FILE_PREFIX}_{county}_{year}.csv")
    
    if should_skip_processing(file_path, year_specific_path, force_recompute):
        log(at="process", county=county, status="skipped_existing", files_at=file_path)
        return   
    
    if os.path.exists(file_path):
        log(
            at="process",
            county=county,
            new_files_downloaded="F",
            files_at=file_path,
        )
        # Even if the raw file exists, we might want to generate the year-specific file.
        data_only_for_year(year, county, file_path)
        return

 

    try:
        # Get centroid coordinates dynamically using geopy.
        coordinates = get_county_coordinates(county)
        if coordinates is None:
            log(
                at="process",
                county=county,
                files_downloaded="F",
                description="could not find centroid"
            )
            return
        
        latitude, longitude = coordinates
        response = fetch_weather_data(latitude, longitude, county)

        if response.status_code == 200:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as file:
                file.write(response.text)
            print(f"Saved TMY data for {county} to {file_path}")
            
            # Now filter the raw weather file for the desired year.
            data_only_for_year(year, county, file_path)
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

def process(base_input_dir, output_dir, scenario, housing_types, year, counties=None, force_recompute=False):
    """
    Processes weather files for given scenarios, housing types, and counties.
    The weather data is fetched from NREL and saved to disk, then filtered to retain
    only the rows for the given 'year'. The target year is passed as a top-level argument.
    """
    for housing_type in housing_types:
        scenario_path = get_scenario_path(base_input_dir, scenario, housing_type)
        counties_list = get_counties(scenario_path, counties)

        for county in counties_list:
            process_county_weather(county, output_dir, scenario, housing_type, year, force_recompute)

if __name__ == '__main__':
    process("data", "data/loadprofiles", "baseline", ["single-family-detached"], 2018, norcal_counties + central_counties + socal_counties)