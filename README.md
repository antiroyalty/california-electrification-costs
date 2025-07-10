# The Economics of Going Electric in California: From Gas to Grid in 2025

### Background

This project models the residential costs of increasing household electrification in California as of May 2025. It is funded by the California Climate Action Initiative and the research is undertaken as part of UC Berkeley's Energy and Resources Group (ERG) in the Energy, Modeling, Analysis and Control (EMAC) lab.

Costs of electrifying, and adopting solar and storage, are presented for each county for single-family detached homes, with utility tariffs from PG&E, SCE, and SDG&E. Electricity costs, gas costs, and capital costs are all considered. For instance, if a gas stove is replaced by an induction stove, the decrease in gas costs, along with the injection of capital cost, and the changes in the energy bill due to the increased electricity consumption are all considered.

### Dependencies

This project requires Python 3 with the following external dependencies:

#### Core Dependencies
- **PySAM** - NREL's System Advisor Model Python wrapper for solar and battery modeling
- **pandas** - Data manipulation and analysis library
- **geopandas** - Geographic data manipulation library
- **folium** - Interactive web maps creation
- **numpy** - Numerical computing library
- **requests** - HTTP library for API calls
- **boto3** - AWS SDK for Python (for accessing building data)
- **botocore** - Low-level interface to AWS services
- **geopy** - Geocoding library
- **python-dotenv** - Environment variable management

#### Additional files and applications
- Get the NREL metadata CSV from Ana (too big to include on Github)
- Get the PVWatts JSON files from SAM_configuration (now should be included as part of Github)
- Download and install the System Advisor Model from NREL for some SAM computational dependencies

#### Development Dependencies
- **pytest** - Testing framework
- **matplotlib** - Plotting library (for notebooks)

#### Installation
Install all dependencies using pip:
```bash
pip install PySAM pandas geopandas folium numpy requests boto3 botocore geopy python-dotenv pytest matplotlib
```

### Getting started
1. Clone the Github repos locally.
2. Install Python 3 and the required dependencies listed above.
3. Obtain an API key for NREL Weather access, and place it in a .env file in the root directory under the variable `NREL_WEATHER_API_KEY`. An NREL Weather API key can be obtained from NREL here: https://developer.nrel.gov/signup/
4. Run `python3 cost_service.py` and explore the results, which should automatically open in your browser. 
5. If you wish to change the scenario that you are running, this can be done in `cost_service.py`. 

### Possible Scenarios
Are currently defined in `cost_service.py`'s SCENARIOS: 

- baseline
- heat_pump
- induction_stove
- heat_pump_and_induction_stove
- water_heating
- heat_pump_and_induction_stove_and_water_heating

If you wish to add a new scenario, you may need to update several other files where these scenarios are used as keys to reference file construction or other behaviors. 
