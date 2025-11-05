"""
Step 17: Net Present Value (NPV) Analysis for Electrification Scenarios

This module outlines the framework for calculating the Net Present Value (NPV) 
of different electrification scenarios compared to baseline gas appliances.

NPV = Sum over analysis period of: (Annual Cash Flow / (1 + discount_rate)^year) - Initial Investment

The NPV calculation helps determine the long-term financial viability of 
electrification investments by accounting for the time value of money.
"""

import os
import pandas as pd
from typing import Dict, List, Tuple
from dataclasses import dataclass
from helpers.main_helpers import log, slugify_county_name, norcal_counties, socal_counties, central_counties
from appliances.electric_base import IncentiveScenario
from step14_build_capital_costs_lifetimes_incentives import process as get_capital_costs

@dataclass
class NPVParameters:
    """Parameters for NPV calculation."""
    discount_rate: float = 0.05  # 5% discount rate (typical for residential investments)
    analysis_period_years: int = 20  # 20-year analysis period
    electricity_price_escalation: float = 0.02  # 2% annual electricity price increase
    gas_price_escalation: float = 0.025  # 2.5% annual gas price increase
    maintenance_escalation: float = 0.02  # 2% annual maintenance cost increase


def outline_npv_calculation_steps():
    """
    Outline the key steps required for NPV analysis of electrification scenarios.
    
    This function serves as documentation for the NPV calculation methodology.
    """
    
    steps = {
        "Step 1": {
            "title": "Load Capital Cost Data",
            "description": "Import appliance capital costs, incentives, and specifications",
            "inputs": [
                "Capital costs from step14 (electric and gas appliances)",
                "Solar and battery storage costs",
                "Incentive scenarios (full, half, none)",
                "Appliance lifetimes and replacement schedules"
            ],
            "outputs": [
                "Initial investment costs by scenario and county",
                "Replacement schedules over analysis period"
            ]
        },
        
        "Step 2": {
            "title": "Load Operating Cost Data", 
            "description": "Import annual energy costs and operational expenses",
            "inputs": [
                "Electricity rates from step11 (TOU rates by county/utility)",
                "Gas rates from step10 (tiered rates by county)",
                "Annual energy consumption profiles from steps 3-6",
                "Maintenance and insurance costs by appliance type"
            ],
            "outputs": [
                "Annual operating costs for baseline scenario",
                "Annual operating costs for electrification scenarios",
                "Annual cost savings (gas baseline - electric scenario)"
            ]
        },
        
        "Step 3": {
            "title": "Calculate Solar and Storage Benefits",
            "description": "Quantify energy cost savings from solar+storage systems",
            "inputs": [
                "Solar generation profiles from step8 (SAM model outputs)",
                "Battery dispatch profiles and grid interaction",
                "Avoided electricity costs from solar self-consumption",
                "Time-of-use rate structures and peak demand charges"
            ],
            "outputs": [
                "Annual electricity bill reductions from solar",
                "Additional savings from battery storage arbitrage",
                "Net metering credits and export values"
            ]
        },
        
        "Step 4": {
            "title": "Project Cash Flows Over Analysis Period",
            "description": "Calculate year-by-year cash flows with escalation rates",
            "inputs": [
                "NPV parameters (discount rate, escalation rates)",
                "Annual cost savings from step 2",
                "Solar/storage benefits from step 3",
                "Appliance replacement schedules",
                "Energy price escalation assumptions"
            ],
            "outputs": [
                "Annual net cash flows by year",
                "Cumulative cash flows",
                "Equipment replacement costs over time"
            ]
        },
        
        "Step 5": {
            "title": "Apply Discount Rate and Calculate NPV",
            "description": "Convert future cash flows to present value",
            "inputs": [
                "Annual cash flows from step 4",
                "Discount rate (typically 3-7% for residential)",
                "Initial capital investment (net of incentives)",
                "Terminal values for remaining appliance life"
            ],
            "outputs": [
                "Present value of each year's cash flow",
                "Net Present Value (NPV) by scenario and county",
                "Payback period and internal rate of return (IRR)"
            ]
        },
        
        "Step 6": {
            "title": "Sensitivity Analysis",
            "description": "Test NPV sensitivity to key assumptions",
            "inputs": [
                "Range of discount rates (3%, 5%, 7%)",
                "Energy price escalation scenarios (low, medium, high)",
                "Different analysis periods (15, 20, 25 years)",
                "Appliance lifetime assumptions"
            ],
            "outputs": [
                "NPV ranges under different scenarios",
                "Break-even analysis for key parameters",
                "Risk assessment and confidence intervals"
            ]
        },
        
        "Step 7": {
            "title": "Generate NPV Results and Visualizations",
            "description": "Create county-level NPV maps and summary tables",
            "inputs": [
                "NPV calculations by county and scenario",
                "Geographic data for mapping",
                "Scenario comparison metrics"
            ],
            "outputs": [
                "NPV maps by electrification scenario",
                "County rankings by NPV attractiveness",
                "Scenario comparison tables",
                "Investment decision matrices"
            ]
        }
    }
    
    return steps


def load_required_data(base_input_dir: str, scenario: str, housing_type: str, counties: List[str]) -> Dict:
    """
    Step 1: Load all required data for NPV calculation.
    
    Args:
        base_input_dir: Base directory for input data
        scenario: Electrification scenario to analyze
        housing_type: Housing type (e.g., "single-family-detached")
        counties: List of counties to analyze
        
    Returns:
        Dictionary containing all loaded data
    """
    log(at="load_required_data", info="loading_data_for_npv", scenario=scenario)
    
    # TODO: Implement data loading
    # - Capital costs from step14
    # - Energy costs from steps 10-11
    # - Energy consumption from steps 3-6
    # - Solar generation from step8
    
    return {
        "capital_costs": None,  # From step14
        "electricity_costs": None,  # From step11
        "gas_costs": None,  # From step10
        "energy_consumption": None,  # From steps 3-6
        "solar_generation": None,  # From step8
    }


def calculate_annual_cash_flows(data: Dict, params: NPVParameters) -> pd.DataFrame:
    """
    Steps 2-4: Calculate annual cash flows over the analysis period.
    
    Args:
        data: Loaded data from load_required_data
        params: NPV calculation parameters
        
    Returns:
        DataFrame with annual cash flows by county and year
    """
    log(at="calculate_annual_cash_flows", info="calculating_cash_flows")
    
    # TODO: Implement cash flow calculation
    # 1. Calculate baseline operating costs (gas scenario)
    # 2. Calculate electrification operating costs
    # 3. Apply price escalation rates
    # 4. Account for appliance replacements
    # 5. Include solar/storage benefits
    
    # Placeholder structure
    cash_flows = pd.DataFrame({
        'county': [],
        'year': [],
        'baseline_cost': [],
        'scenario_cost': [],
        'annual_savings': [],
        'cumulative_savings': []
    })
    
    return cash_flows


def calculate_npv(cash_flows: pd.DataFrame, initial_investment: pd.DataFrame, 
                 params: NPVParameters) -> pd.DataFrame:
    """
    Step 5: Calculate Net Present Value for each county and scenario.
    
    Args:
        cash_flows: Annual cash flows from calculate_annual_cash_flows
        initial_investment: Initial capital investment by county
        params: NPV calculation parameters
        
    Returns:
        DataFrame with NPV results by county
    """
    log(at="calculate_npv", info="calculating_npv")
    
    # TODO: Implement NPV calculation
    # NPV = -Initial_Investment + Sum(Annual_Cash_Flow / (1 + discount_rate)^year)
    
    # Placeholder structure
    npv_results = pd.DataFrame({
        'county': [],
        'scenario': [],
        'initial_investment': [],
        'total_pv_savings': [],
        'npv': [],
        'payback_period': [],
        'irr': []
    })
    
    return npv_results


def sensitivity_analysis(base_npv: pd.DataFrame, data: Dict) -> Dict:
    """
    Step 6: Perform sensitivity analysis on key parameters.
    
    Args:
        base_npv: Base case NPV results
        data: Input data for recalculation
        
    Returns:
        Dictionary with sensitivity analysis results
    """
    log(at="sensitivity_analysis", info="running_sensitivity_analysis")
    
    # TODO: Implement sensitivity analysis
    # - Vary discount rate (3%, 5%, 7%)
    # - Vary energy price escalation rates
    # - Vary analysis period
    # - Monte Carlo simulation for uncertainty
    
    return {
        "discount_rate_sensitivity": None,
        "price_escalation_sensitivity": None,
        "analysis_period_sensitivity": None,
        "monte_carlo_results": None
    }


def generate_npv_outputs(npv_results: pd.DataFrame, sensitivity: Dict, 
                        base_output_dir: str, scenario: str, housing_type: str) -> None:
    """
    Step 7: Generate NPV maps, tables, and visualizations.
    
    Args:
        npv_results: NPV calculation results
        sensitivity: Sensitivity analysis results
        base_output_dir: Output directory
        scenario: Electrification scenario
        housing_type: Housing type
    """
    log(at="generate_npv_outputs", info="generating_npv_outputs")
    
    # TODO: Implement output generation
    # - Create NPV maps using maps_helpers.py
    # - Generate summary tables
    # - Create scenario comparison charts
    # - Export results to CSV/HTML
    
    output_dir = os.path.join(base_output_dir, "npv_analysis")
    os.makedirs(output_dir, exist_ok=True)
    
    # Save NPV results
    npv_file = f"npv_results_{scenario}_{housing_type.replace('-', '_')}.csv"
    npv_results.to_csv(os.path.join(output_dir, npv_file), index=False)
    
    log(at="generate_npv_outputs", info="npv_outputs_saved", output_dir=output_dir)


def process(base_input_dir: str, base_output_dir: str, scenario: str, 
           housing_type: str, counties: List[str], 
           params: NPVParameters = NPVParameters()) -> Dict:
    """
    Main NPV analysis processing function.
    
    Args:
        base_input_dir: Input data directory
        base_output_dir: Output directory
        scenario: Electrification scenario to analyze
        housing_type: Housing type
        counties: List of counties to analyze
        params: NPV calculation parameters
        
    Returns:
        Dictionary with NPV analysis results
    """
    log(at="step17_npv", info="starting_npv_analysis", scenario=scenario)
    
    # Step 1: Load required data
    data = load_required_data(base_input_dir, scenario, housing_type, counties)
    
    # Steps 2-4: Calculate cash flows
    cash_flows = calculate_annual_cash_flows(data, params)
    
    # Step 5: Calculate NPV
    # TODO: Load initial investment data
    initial_investment = pd.DataFrame()  # Placeholder
    npv_results = calculate_npv(cash_flows, initial_investment, params)
    
    # Step 6: Sensitivity analysis
    sensitivity = sensitivity_analysis(npv_results, data)
    
    # Step 7: Generate outputs
    generate_npv_outputs(npv_results, sensitivity, base_output_dir, scenario, housing_type)
    
    log(at="step17_npv", info="npv_analysis_completed")
    
    return {
        "npv_results": npv_results,
        "cash_flows": cash_flows,
        "sensitivity": sensitivity,
        "parameters": params
    }


if __name__ == "__main__":
    import argparse
    from scenarios import SCENARIOS
    
    parser = argparse.ArgumentParser(description="NPV Analysis for Electrification Scenarios")
    parser.add_argument("scenario", choices=list(SCENARIOS.keys()),
                       help="Electrification scenario to analyze")
    parser.add_argument("--discount-rate", type=float, default=0.05,
                       help="Discount rate for NPV calculation (default: 0.05)")
    parser.add_argument("--analysis-period", type=int, default=20,
                       help="Analysis period in years (default: 20)")
    
    args = parser.parse_args()
    
    # Set up parameters
    params = NPVParameters(
        discount_rate=args.discount_rate,
        analysis_period_years=args.analysis_period
    )
    
    housing_type = "single-family-detached"
    all_counties = norcal_counties + socal_counties + central_counties
    
    # Print methodology outline
    print("NPV Analysis Methodology:")
    print("=" * 50)
    steps = outline_npv_calculation_steps()
    for step_key, step_info in steps.items():
        print(f"\n{step_key}: {step_info['title']}")
        print(f"Description: {step_info['description']}")
        print(f"Key Inputs: {', '.join(step_info['inputs'][:2])}...")
    
    print(f"\nRunning NPV analysis for scenario: {args.scenario}")
    print("Note: This is currently a framework outline. Implementation needed.")
    
    # result = process(
    #     base_input_dir="data/loadprofiles",
    #     base_output_dir="data/loadprofiles",
    #     scenario=args.scenario,
    #     housing_type=housing_type,
    #     counties=all_counties,
    #     params=params
    # )