
#!/usr/bin/env python3
"""
Example usage of ElectricHeating and InductionStove appliance classes.

This script demonstrates how to use the appliance classes to get cost information,
incentive breakdowns, and payback calculations for different scenarios.
"""

from appliances.electric_heating import ElectricHeatingAppliance
from appliances.induction_stove import InductionStoveAppliance
from appliances.electric_vehicle import ElectricVehicleAppliance
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


def demonstrate_electric_vehicle():
    """Demonstrate ElectricVehicleAppliance usage."""
    print("\n" + "=" * 60)
    print("ELECTRIC VEHICLE APPLIANCE")
    print("=" * 60)
    
    ev = ElectricVehicleAppliance()
    
    print(f"Appliance Name: {ev.name}")
    print(f"Vehicle Type: {ev.vehicle_type}")
    print(f"Base Cost: ${ev.base_cost:,.2f}")
    print(f"Lifetime: {ev.lifetime_years} years")
    print(f"Number of Incentives: {len(ev.incentives)}")
    
    # Show incentive details
    print("\nAvailable Incentives:")
    for i, incentive in enumerate(ev.incentives, 1):
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
        breakdown = ev.get_cost_breakdown(scenario)
        
        print(f"Base Cost: ${breakdown['base_cost']:,.2f}")
        print(f"Total Incentives: ${breakdown['total_incentives']:,.2f}")
        print(f"Net Cost: ${breakdown['net_cost']:,.2f}")
        print(f"Annual Cost: ${breakdown['cost_per_year']:,.2f}")
        
        # Show total cost of ownership
        tco = ev.get_total_cost_of_ownership(scenario=scenario)
        print(f"Total Cost of Ownership: ${tco['net_total_cost_of_ownership']:,.2f}")
        print(f"Payback Period: {tco['payback_period_years']:.1f} years")


def compare_all_appliances():
    """Compare all three appliances side by side."""
    print("\n" + "=" * 80)
    print("ALL APPLIANCES COMPARISON")
    print("=" * 80)
    
    heat_pump = ElectricHeatingAppliance()
    stove = InductionStoveAppliance()
    ev = ElectricVehicleAppliance()
    
    scenario = IncentiveScenario.FULL_INCENTIVES
    hp_breakdown = heat_pump.get_cost_breakdown(scenario)
    stove_breakdown = stove.get_cost_breakdown(scenario)
    ev_breakdown = ev.get_cost_breakdown(scenario)
    
    print(f"{'Metric':<25} {'Heat Pump':<12} {'Induction':<12} {'Electric Vehicle':<15}")
    print("-" * 80)
    print(f"{'Base Cost':<25} ${hp_breakdown['base_cost']:>8,.0f}    ${stove_breakdown['base_cost']:>8,.0f}    ${ev_breakdown['base_cost']:>11,.0f}")
    print(f"{'Total Incentives':<25} ${hp_breakdown['total_incentives']:>8,.0f}    ${stove_breakdown['total_incentives']:>8,.0f}    ${ev_breakdown['total_incentives']:>11,.0f}")
    print(f"{'Net Cost':<25} ${hp_breakdown['net_cost']:>8,.0f}    ${stove_breakdown['net_cost']:>8,.0f}    ${ev_breakdown['net_cost']:>11,.0f}")
    print(f"{'Lifetime (years)':<25} {hp_breakdown['lifetime_years']:>9}    {stove_breakdown['lifetime_years']:>9}    {ev_breakdown['lifetime_years']:>12}")
    print(f"{'Annual Cost':<25} ${hp_breakdown['cost_per_year']:>8,.0f}    ${stove_breakdown['cost_per_year']:>8,.0f}    ${ev_breakdown['cost_per_year']:>11,.0f}")
    
    # EV total cost of ownership
    ev_tco = ev.get_total_cost_of_ownership()
    print(f"\nElectric Vehicle Total Cost of Ownership:")
    print(f"  Net purchase cost: ${ev_tco['net_purchase_cost']:,.0f}")
    print(f"  Total savings over {ev_tco['lifetime_years']} years: ${ev_tco['total_savings_over_lifetime']:,.0f}")
    print(f"  Net TCO: ${ev_tco['net_total_cost_of_ownership']:,.0f}")
    print(f"  Payback period: {ev_tco['payback_period_years']:.1f} years")


if __name__ == "__main__":
    demonstrate_electric_heating()
    demonstrate_induction_stove()
    demonstrate_electric_vehicle()
    compare_all_appliances()