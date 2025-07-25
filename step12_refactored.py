"""
Step 12: Calculate Capital Costs and Payback Periods for Solar + Storage Systems

This module calculates the total installation costs and payback periods for solar + storage
systems across California counties, taking into account utility rate plans and regional variations.
"""

import os
import pandas as pd
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path

from helpers import get_counties, get_scenario_path, to_decimal_number
from utility_helpers import get_utility_for_county


# =============================================================================
# Configuration and Constants
# =============================================================================

@dataclass(frozen=True)
class SolarCosts:
    """Solar panel cost configuration."""
    dollars_per_watt: float = 2.83          # $/W - Tesla solar cost breakdown
    installation_labor_pct: float = 0.07    # 7% - Installation labor percentage  
    design_overhead_pct: float = 0.28       # 28% - Design, engineering, overhead percentage

@dataclass(frozen=True) 
class StorageCosts:
    """Energy storage cost configuration."""
    powerwall_13_5kwh: float = 10748         # $ - Tesla Powerwall cost after incentives

@dataclass(frozen=True)
class EVChargingCosts:
    """EV charging equipment cost configuration."""
    tesla_wall_connector: float = 1150      # $ - Tesla wall connector
    universal_wall_connector: float = 1350  # $ - Universal wall connector

@dataclass(frozen=True)
class CapitalCostConfig:
    """Complete capital cost configuration."""
    solar: SolarCosts = field(default_factory=SolarCosts)
    storage: StorageCosts = field(default_factory=StorageCosts) 
    ev_charging: EVChargingCosts = field(default_factory=EVChargingCosts)

@dataclass(frozen=True)
class FilePathConfig:
    """File paths and naming conventions."""
    electrified_assets_file: str = "electrified_assets.csv"
    capital_costs_folder: str = "CAPITAL_COSTS"
    results_folder: str = "results"
    totals_subfolder: str = "totals" 
    solarstorage_subfolder: str = "solarstorage"
    totals_file_prefix: str = "RESULTS_total_annual_costs"
    output_filename: str = "system_payback_by_county.csv"

# Default configuration instances
COST_CONFIG = CapitalCostConfig()
PATH_CONFIG = FilePathConfig()


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class CountySystemData:
    """Data for a county's solar + storage system."""
    county_name: str
    solar_capacity_kw: float
    utility: str
    baseline_annual_cost: float
    solarstorage_annual_cost: float
    
    @property
    def annual_savings(self) -> float:
        """Calculate annual cost savings."""
        return self.baseline_annual_cost - self.solarstorage_annual_cost

@dataclass
class SystemCostAnalysis:
    """Results of system cost and payback analysis."""
    total_system_cost: float
    payback_period_years: float
    annual_savings: float
    solar_cost: float
    storage_cost: float
    
    def to_dict(self, utility: str, rate_plan_key: str) -> Dict[str, float]:
        """Convert to dictionary for DataFrame creation."""
        prefix = f"{utility}.{rate_plan_key}"
        return {
            f"{prefix}.total_cost": to_decimal_number(self.total_system_cost),
            f"{prefix}.payback_years": to_decimal_number(self.payback_period_years), 
            f"{prefix}.annual_savings": to_decimal_number(self.annual_savings),
            f"{prefix}.solar_cost": to_decimal_number(self.solar_cost),
            f"{prefix}.storage_cost": to_decimal_number(self.storage_cost)
        }


# =============================================================================
# File Operations
# =============================================================================

class FileHandler:
    """Handles all file I/O operations for capital cost analysis."""
    
    @staticmethod
    def extract_timestamp_from_filename(filename: str) -> datetime:
        """Extract timestamp from filename with format: prefix_county_YYYYMMDD_HH.csv"""
        parts = filename.rstrip(".csv").split("_")
        if len(parts) < 2:
            raise ValueError(f"Invalid filename format: {filename}")
        
        timestamp_str = f"{parts[-2]}_{parts[-1]}"
        return datetime.strptime(timestamp_str, "%Y%m%d_%H")

    @classmethod
    def get_latest_csv_file(cls, directory: Path, prefix: str) -> Path:
        """Get the most recent CSV file in directory with given prefix."""
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
            
        csv_files = [f for f in directory.iterdir() 
                    if f.name.startswith(prefix) and f.name.endswith(".csv")]
        
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {directory} with prefix '{prefix}'")
            
        latest_file = max(csv_files, key=lambda f: cls.extract_timestamp_from_filename(f.name))
        return latest_file

    @classmethod
    def load_cost_data(cls, county_dir: Path, subfolder: str, file_prefix: str, 
                      scenario_row: int = 0) -> pd.Series:
        """Load cost data from CSV file and return specified row as Series."""
        results_dir = county_dir / PATH_CONFIG.results_folder / subfolder
        county_name = county_dir.name
        full_prefix = f"{file_prefix}_{county_name}_"
        
        file_path = cls.get_latest_csv_file(results_dir, full_prefix)
        
        df = pd.read_csv(file_path, index_col="scenario")
        if df.empty:
            raise ValueError(f"Empty data file: {file_path}")
            
        # For solarstorage subfolder, use second row (solar+storage scenario)
        # For totals subfolder, use first row (baseline scenario)  
        row_index = 1 if subfolder == PATH_CONFIG.solarstorage_subfolder else 0
        
        if len(df) <= row_index:
            raise ValueError(f"Not enough rows in {file_path}, need at least {row_index + 1}")
            
        return df.iloc[row_index]

    @staticmethod
    def load_electrified_assets(scenario_path: Path) -> Dict[str, float]:
        """Load solar capacity data for all counties from electrified assets file."""
        assets_file = scenario_path / PATH_CONFIG.capital_costs_folder / PATH_CONFIG.electrified_assets_file
        
        if not assets_file.exists():
            raise FileNotFoundError(f"Electrified assets file not found: {assets_file}")
        
        df = pd.read_csv(assets_file)
        required_columns = ["County", "Solar Capacity (kW)"]
        
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing columns in {assets_file}: {missing_columns}")
        
        return df.set_index("County")["Solar Capacity (kW)"].to_dict()


# =============================================================================
# Cost Calculation Engine
# =============================================================================

class CostCalculator:
    """Handles all cost calculations for solar + storage systems."""
    
    def __init__(self, config: CapitalCostConfig = COST_CONFIG):
        self.config = config
    
    def calculate_solar_cost(self, capacity_kw: float) -> float:
        """Calculate total solar installation cost including labor and overhead."""
        # Convert kW to watts and calculate base panel cost
        panel_cost_base = capacity_kw * 1000 * self.config.solar.dollars_per_watt
        
        # Add labor and overhead costs
        total_multiplier = (1 + 
                          self.config.solar.installation_labor_pct + 
                          self.config.solar.design_overhead_pct)
        
        return panel_cost_base * total_multiplier
    
    def calculate_storage_cost(self, num_powerwalls: int = 1) -> float:
        """Calculate total storage cost for specified number of Powerwalls."""
        return num_powerwalls * self.config.storage.powerwall_13_5kwh
    
    def analyze_system_economics(self, system_data: CountySystemData) -> SystemCostAnalysis:
        """Perform complete economic analysis of solar + storage system."""
        solar_cost = self.calculate_solar_cost(system_data.solar_capacity_kw)
        storage_cost = self.calculate_storage_cost()  # Default: 1 Powerwall
        
        total_cost = solar_cost + storage_cost
        annual_savings = system_data.annual_savings
        
        # Calculate payback period, handle division by zero
        if annual_savings <= 0:
            payback_years = float('inf')
        else:
            payback_years = total_cost / annual_savings
            
        return SystemCostAnalysis(
            total_system_cost=total_cost,
            payback_period_years=payback_years,
            annual_savings=annual_savings,
            solar_cost=solar_cost,
            storage_cost=storage_cost
        )


# =============================================================================
# Data Processing Pipeline
# =============================================================================

class CapitalCostProcessor:
    """Main processor for capital cost and payback analysis."""
    
    def __init__(self, 
                 cost_calculator: CostCalculator = None,
                 file_handler: FileHandler = None):
        self.calculator = cost_calculator or CostCalculator()
        self.file_handler = file_handler or FileHandler()
    
    def build_rate_plan_column_name(self, utility: str, elec_rate: str, gas_rate: str) -> str:
        """Build standardized column name for rate plan combination."""
        return f"total.{utility}.{elec_rate}+{utility}.{gas_rate}"
    
    def extract_county_data(self, county: str, county_dir: Path, 
                          assets_mapping: Dict[str, float],
                          utility: str, rate_plan_column: str) -> CountySystemData:
        """Extract all required data for a single county."""
        # Load baseline and solar+storage cost data
        baseline_data = self.file_handler.load_cost_data(
            county_dir, PATH_CONFIG.totals_subfolder, PATH_CONFIG.totals_file_prefix
        )
        solarstorage_data = self.file_handler.load_cost_data(
            county_dir, PATH_CONFIG.solarstorage_subfolder, PATH_CONFIG.totals_file_prefix
        )
        
        # Validate that required column exists in both datasets
        if rate_plan_column not in baseline_data.index:
            raise ValueError(f"Rate plan column '{rate_plan_column}' not found in baseline data for {county}")
        if rate_plan_column not in solarstorage_data.index:
            raise ValueError(f"Rate plan column '{rate_plan_column}' not found in solarstorage data for {county}")
        
        # Get solar capacity for this county
        if county not in assets_mapping:
            raise ValueError(f"Solar capacity not found for county '{county}' in assets mapping")
        
        return CountySystemData(
            county_name=county,
            solar_capacity_kw=assets_mapping[county],
            utility=utility,
            baseline_annual_cost=baseline_data[rate_plan_column],
            solarstorage_annual_cost=solarstorage_data[rate_plan_column]
        )
    
    def process_county(self, county: str, scenario_path: Path,
                      assets_mapping: Dict[str, float],
                      desired_rate_plans: Dict[str, Dict[str, str]]) -> Optional[Dict[str, any]]:
        """Process a single county and return results dictionary."""
        county_dir = scenario_path / county
        
        try:
            # Get utility for this county
            utility = get_utility_for_county(county)
            if not utility:
                print(f"Warning: No utility found for county {county}, skipping")
                return None
                
            # Check if utility is in our desired rate plans
            if utility not in desired_rate_plans:
                print(f"Warning: Utility {utility} for county {county} not in desired rate plans, skipping")
                return None
            
            # Build rate plan identifiers
            elec_rate = desired_rate_plans[utility]["electricity"]
            gas_rate = desired_rate_plans[utility]["gas"]
            rate_plan_column = self.build_rate_plan_column_name(utility, elec_rate, gas_rate)
            rate_plan_key = f"{elec_rate}+{gas_rate}"
            
            # Extract county data
            system_data = self.extract_county_data(
                county, county_dir, assets_mapping, utility, rate_plan_column
            )
            
            # Perform economic analysis
            analysis = self.calculator.analyze_system_economics(system_data)
            
            # Build results dictionary
            results = {"County": county}
            results.update(analysis.to_dict(utility, rate_plan_key))
            
            return results
            
        except Exception as e:
            print(f"Error processing county {county}: {e}")
            return None
    
    def process_all_counties(self, 
                           base_input_dir: str, 
                           base_output_dir: str,
                           scenario: str,
                           housing_type: str, 
                           counties: List[str],
                           desired_rate_plans: Dict[str, Dict[str, str]]) -> None:
        """Process all counties and generate final results CSV."""
        
        # Setup paths
        scenario_path = Path(get_scenario_path(base_input_dir, scenario, housing_type))
        valid_counties = get_counties(scenario_path, counties)
        
        # Load solar capacity mapping
        try:
            assets_mapping = self.file_handler.load_electrified_assets(scenario_path)
        except Exception as e:
            print(f"Error loading electrified assets: {e}")
            return
            
        print(f"Processing {len(valid_counties)} counties for scenario '{scenario}'...")
        
        # Process each county
        results = []
        for county in valid_counties:
            county_results = self.process_county(
                county, scenario_path, assets_mapping, desired_rate_plans
            )
            if county_results:
                results.append(county_results)
        
        # Generate output
        if results:
            results_df = pd.DataFrame(results).set_index("County")
            
            # Ensure output directory exists
            output_dir = Path(base_output_dir) / scenario / housing_type / PATH_CONFIG.capital_costs_folder
            output_dir.mkdir(parents=True, exist_ok=True)
            
            output_file = output_dir / PATH_CONFIG.output_filename
            results_df.to_csv(output_file)
            
            print(f"Successfully processed {len(results)} counties")
            print(f"Results saved to: {output_file}")
        else:
            print("No valid results generated")


# =============================================================================
# Main Interface
# =============================================================================

def process(base_input_dir: str, 
           base_output_dir: str,
           scenario: str,
           housing_type: str,
           counties: List[str], 
           desired_rate_plans: Dict[str, Dict[str, str]]) -> None:
    """
    Main entry point for capital cost and payback period analysis.
    
    Args:
        base_input_dir: Directory containing input data
        base_output_dir: Directory for output files  
        scenario: Scenario name (e.g., 'heat_pump')
        housing_type: Housing type (e.g., 'single-family-detached')
        counties: List of county names to process
        desired_rate_plans: Dictionary mapping utility -> {electricity: rate, gas: rate}
            Example: {
                "PG&E": {"electricity": "E-TOU-D", "gas": "G-1"},
                "SCE": {"electricity": "TOU-D-4-9PM", "gas": "GR"}
            }
    """
    processor = CapitalCostProcessor()
    processor.process_all_counties(
        base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans
    )


# =============================================================================
# Example Usage
# =============================================================================

if __name__ == '__main__':
    from helpers import norcal_counties, socal_counties, central_counties
    
    # Configuration
    base_input_dir = "data/loadprofiles"
    base_output_dir = "data/loadprofiles" 
    scenario = "baseline"
    housing_type = "single-family-detached"
    counties = norcal_counties + socal_counties + central_counties
    
    desired_rate_plans = {
        "PG&E": {
            "electricity": "E-TOU-D",
            "gas": "G-1"
        },
        "SCE": {
            "electricity": "TOU-D-4-9PM", 
            "gas": "GR"
        },
        "SDG&E": {
            "electricity": "TOU-DR1",
            "gas": "GR" 
        }
    }
    
    process(base_input_dir, base_output_dir, scenario, housing_type, counties, desired_rate_plans)