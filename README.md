# The Economics of Going Electric in California: From Gas to Grid in 2025

### Background

This project models the residential costs of increasing household electrification in California as of May 2025. It is funded by the California Climate Action Initiative and the research is undertaken as part of UC Berkeley's Energy and Resources Group (ERG) in the Energy, Modeling, Analysis and Control (EMAC) lab.

Costs of electrifying, and adopting solar and storage, are presented for each county for single-family detached homes, with utility tariffs from PG&E, SCE, and SDG&E. Electricity costs, gas costs, and capital costs are all considered. For instance, if a gas stove is replaced by an induction stove, the decrease in gas costs, along with the injection of capital cost, and the changes in the energy bill due to the increased electricity consumption are all considered.

### Getting started
1. Clone the Github repos locally.
2. Install `python3` and related dependencies and python tools. 
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
