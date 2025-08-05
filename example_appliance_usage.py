
git#!/usr/bin/env python3
"""
Example usage of ElectricHeating and InductionStove appliance classes.

This script demonstrates how to use the appliance classes to get cost information,
incentive breakdowns, and payback calculations for different scenarios.
"""

from appliances.electric_heating import ElectricHeatingAppliance
from appliances.induction_stove import InductionStoveAppliance
from step15_build_capital_costs_lifetimes_incentives import IncentiveScenario

def demonstrate_electric_heating():
    """Demonstrate ElectricHeatingAppliance usage."""
    print("=" * 60)
    print("ELECTRIC HEATING (HEAT PUMP)")
    print("=" * 60)
    
    heat_pump = ElectricHeatingAppliance()
    
    # Customize the parameters if needed
    # heat_pump = ElectricHeatingAppliance(
    #     heating_type="heat_pump",
    #     base_cost=20000.0,
    #     lifetime_years=18
    # )
    
    print(f"Appliance Name: {heat_pump.name}")
    print(f"Heating Type: {heat_pump.heating_type}")
    print(f"Base Cost: ${heat_pump.base_cost:,.2f}")
    print(f"Lifetime: {heat_pump.lifetime_years} years")
    print(f"Number of Incentives: {len(heat_pump.incentives)}")
    
    print("\nAvailable Incentives:")
    for i, incentive in enumerate(heat_pump.incentives, 1):
        print(f"  {i}. {incentive.name}")
        print(f"     Value: {incentive.value}{incentive.unit}")
        if incentive.max_value:
            print(f"     Max Value: ${incentive.max_value:,.2f}")
        print(f"     Description: {incentive.description}")
        print()
    
    # Show cost breakdown for different scenarios
    scenarios = [
        IncentiveScenario.FULL_INCENTIVES,
        IncentiveScenario.HALF_INCENTIVES,
        IncentiveScenario.NO_INCENTIVES
    ]
    
    for scenario in scenarios:
        print(f"\n--- {scenario.value.upper().replace('_', ' ')} ---")
        breakdown = heat_pump.get_cost_breakdown(scenario)
        
        print(f"Base Cost: ${breakdown['base_cost']:,.2f}")
        print(f"Total Incentives: ${breakdown['total_incentives']:,.2f}")
        print(f"Net Cost: ${breakdown['net_cost']:,.2f}")
        print(f"Annual Cost: ${breakdown['cost_per_year']:,.2f}")
        
        # Show payback calculations
        for target_years in [5, 10, 15]:
            required_savings = heat_pump.get_annual_cost_savings_needed_for_payback(
                target_years, scenario
            )
            print(f"  Savings needed for {target_years}-year payback: ${required_savings:,.2f}/year")


def demonstrate_induction_stove():
    """Demonstrate InductionStoveAppliance usage."""
    print("\n" + "=" * 60)
    print("INDUCTION STOVE APPLIANCE")
    print("=" * 60)
    
    stove = InductionStoveAppliance()
    
    print(f"Appliance Name: {stove.name}")
    print(f"Stove Type: {stove.stove_type}")
    print(f"Base Cost: ${stove.base_cost:,.2f}")
    print(f"Lifetime: {stove.lifetime_years} years")
    print(f"Number of Incentives: {len(stove.incentives)}")
    
    # Show incentive details
    print("\nAvailable Incentives:")
    for i, incentive in enumerate(stove.incentives, 1):
        print(f"  {i}. {incentive.name}")
        print(f"     Value: ${incentive.value}{incentive.unit}")
        if incentive.max_value:
            print(f"     Max Value: ${incentive.max_value:,.2f}")
        print(f"     Description: {incentive.description}")
        print()
    
    scenarios = [
        IncentiveScenario.FULL_INCENTIVES,
        IncentiveScenario.HALF_INCENTIVES,
        IncentiveScenario.NO_INCENTIVES
    ]
    
    for scenario in scenarios:
        print(f"\n--- {scenario.value.upper().replace('_', ' ')} ---")
        breakdown = stove.get_cost_breakdown(scenario)
        
        print(f"Base Cost: ${breakdown['base_cost']:,.2f}")
        print(f"Total Incentives: ${breakdown['total_incentives']:,.2f}")
        print(f"Net Cost: ${breakdown['net_cost']:,.2f}")
        print(f"Annual Cost: ${breakdown['cost_per_year']:,.2f}")
        
        # Show payback calculations
        for target_years in [3, 5, 10]:
            required_savings = stove.get_annual_cost_savings_needed_for_payback(
                target_years, scenario
            )
            print(f"  Savings needed for {target_years}-year payback: ${required_savings:,.2f}/year")


def compare_appliances():
    """Compare both appliances side by side."""
    print("\n" + "=" * 60)
    print("APPLIANCE COMPARISON")
    print("=" * 60)
    
    heat_pump = ElectricHeatingAppliance()
    stove = InductionStoveAppliance()
    
    scenario = IncentiveScenario.FULL_INCENTIVES
    hp_breakdown = heat_pump.get_cost_breakdown(scenario)
    stove_breakdown = stove.get_cost_breakdown(scenario)
    
    print(f"{'Metric':<30} {'Heat Pump':<15} {'Induction Stove':<15}")
    print("-" * 60)
    print(f"{'Base Cost':<30} ${hp_breakdown['base_cost']:>10,.0f}     ${stove_breakdown['base_cost']:>10,.0f}")
    print(f"{'Total Incentives':<30} ${hp_breakdown['total_incentives']:>10,.0f}     ${stove_breakdown['total_incentives']:>10,.0f}")
    print(f"{'Net Cost':<30} ${hp_breakdown['net_cost']:>10,.0f}     ${stove_breakdown['net_cost']:>10,.0f}")
    print(f"{'Lifetime (years)':<30} {hp_breakdown['lifetime_years']:>11}     {stove_breakdown['lifetime_years']:>11}")
    print(f"{'Annual Cost':<30} ${hp_breakdown['cost_per_year']:>10,.0f}     ${stove_breakdown['cost_per_year']:>10,.0f}")
    
    # Payback comparison for $500/year savings
    annual_savings = 500
    hp_payback = hp_breakdown['net_cost'] / annual_savings
    stove_payback = stove_breakdown['net_cost'] / annual_savings
    
    print(f"\nWith ${annual_savings}/year savings:")
    print(f"  Heat Pump Payback: {hp_payback:.1f} years")
    print(f"  Induction Stove Payback: {stove_payback:.1f} years")


if __name__ == "__main__":
    demonstrate_electric_heating()
    demonstrate_induction_stove()
    compare_appliances()