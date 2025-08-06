
#!/usr/bin/env python3
"""
Example usage of ElectricHeating and InductionStove appliance classes.

This script demonstrates how to use the appliance classes to get cost information,
incentive breakdowns, and payback calculations for different scenarios.
"""

from appliances.electric_heating import ElectricHeatingAppliance
from appliances.electric_cooking import ElectricCookingAppliance
from appliances.electric_water_heating import ElectricWaterHeatingAppliance
from appliances.electric_vehicle import ElectricVehicleAppliance
from appliances.gas_stove import GasStoveAppliance
from appliances.gas_heating import GasHeatingAppliance
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


def demonstrate_electric_cooking():
    """Demonstrate ElectricCookingAppliance usage."""
    print("\n" + "=" * 60)
    print("ELECTRIC COOKING APPLIANCE")
    print("=" * 60)
    
    stove = ElectricCookingAppliance()
    
    print(f"Appliance Name: {stove.name}")
    print(f"Cooking Type: {stove.cooking_type}")
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


def demonstrate_gas_stove():
    """Demonstrate GasStoveAppliance usage."""
    print("\n" + "=" * 60)
    print("GAS STOVE APPLIANCE")
    print("=" * 60)
    
    gas_stove = GasStoveAppliance()
    
    print(f"Appliance Name: {gas_stove.name}")
    print(f"Stove Type: {gas_stove.stove_type}")
    print(f"Base Cost: ${gas_stove.base_cost:,.2f}")
    print(f"Lifetime: {gas_stove.lifetime_years} years")
    print(f"Efficiency: {gas_stove.efficiency:.1%}")
    
    # Show cost breakdown
    breakdown = gas_stove.get_cost_breakdown()
    print(f"\n--- COST BREAKDOWN ---")
    print(f"Base Cost: ${breakdown['base_cost']:,.2f}")
    print(f"Net Cost: ${breakdown['net_cost']:,.2f}")
    print(f"Annual Cost: ${breakdown['annual_cost']:,.2f}")
    print(f"Has Incentives: {breakdown['has_incentives']}")
    
    # Show total cost of ownership
    tco = gas_stove.get_total_cost_of_ownership()
    print(f"\n--- TOTAL COST OF OWNERSHIP ---")
    print(f"Annual Gas Cost: ${tco['annual_operating_cost']:,.2f}")
    print(f"Total Operating Cost: ${tco['total_operating_cost_over_lifetime']:,.2f}")
    print(f"Total Cost of Ownership: ${tco['total_cost_of_ownership']:,.2f}")
    
    # Compare to electric cooking
    electric_cooking = ElectricCookingAppliance()
    electric_cooking_breakdown = electric_cooking.get_cost_breakdown(IncentiveScenario.FULL_INCENTIVES)
    
    comparison = gas_stove.compare_to_induction(
        induction_net_cost=electric_cooking_breakdown['net_cost'],
        annual_gas_cost=tco['annual_operating_cost'],
        annual_electricity_cost=35.0  # Estimated annual electricity cost for induction cooking
    )
    
    print(f"\n--- COMPARISON TO ELECTRIC COOKING ---")
    print(f"Annual Fuel Savings: ${comparison['annual_fuel_savings']:,.2f}")
    print(f"Payback Period: {comparison['payback_period_years']:.1f} years")
    print(f"Net Lifetime Benefit: ${comparison['net_lifetime_benefit']:,.2f}")
    print(f"Recommendation: {comparison['recommendation']}")
    print(f"Efficiency Improvement: {comparison['efficiency_comparison']['efficiency_improvement']:.1f}x")


def compare_cooking_options():
    """Compare gas stove vs electric cooking side by side."""
    print("\n" + "=" * 70)
    print("COOKING APPLIANCES COMPARISON")
    print("=" * 70)
    
    gas_stove = GasStoveAppliance()
    electric_cooking = ElectricCookingAppliance()
    
    gas_breakdown = gas_stove.get_cost_breakdown()
    electric_cooking_breakdown = electric_cooking.get_cost_breakdown(IncentiveScenario.FULL_INCENTIVES)
    gas_tco = gas_stove.get_total_cost_of_ownership()
    
    print(f"{'Metric':<30} {'Gas Stove':<15} {'Electric Cooking':<15}")
    print("-" * 70)
    print(f"{'Base Cost':<30} ${gas_breakdown['base_cost']:>10,.0f}     ${electric_cooking_breakdown['base_cost']:>10,.0f}")
    print(f"{'Incentives':<30} ${0:>10,.0f}     ${electric_cooking_breakdown['total_incentives']:>10,.0f}")
    print(f"{'Net Cost':<30} ${gas_breakdown['net_cost']:>10,.0f}     ${electric_cooking_breakdown['net_cost']:>10,.0f}")
    print(f"{'Efficiency':<30} {gas_breakdown['efficiency']:>11.1%}     {'85.0%':>11}")
    print(f"{'Annual Equipment Cost':<30} ${gas_breakdown['annual_cost']:>10,.0f}     ${electric_cooking_breakdown['cost_per_year']:>10,.0f}")
    print(f"{'Annual Operating Cost':<30} ${gas_tco['annual_operating_cost']:>10,.0f}     ${'35':>10}")
    
    # Calculate total costs
    gas_total_annual = gas_breakdown['annual_cost'] + gas_tco['annual_operating_cost']
    electric_cooking_total_annual = electric_cooking_breakdown['cost_per_year'] + 35
    
    print(f"{'Total Annual Cost':<30} ${gas_total_annual:>10,.0f}     ${electric_cooking_total_annual:>10,.0f}")
    
    savings = gas_total_annual - electric_cooking_total_annual
    print(f"\nElectric Cooking Annual Savings: ${savings:,.2f}")
    if savings > 0:
        payback = electric_cooking_breakdown['net_cost'] / savings
        print(f"Electric Cooking Payback Period: {payback:.1f} years")


def compare_all_appliances():
    """Compare all appliances side by side."""
    print("\n" + "=" * 90)
    print("ALL APPLIANCES COMPARISON")
    print("=" * 90)
    
    heat_pump = ElectricHeatingAppliance()
    electric_cooking = ElectricCookingAppliance()
    gas_stove = GasStoveAppliance()
    ev = ElectricVehicleAppliance()
    
    scenario = IncentiveScenario.FULL_INCENTIVES
    hp_breakdown = heat_pump.get_cost_breakdown(scenario)
    electric_cooking_breakdown = electric_cooking.get_cost_breakdown(scenario)
    gas_breakdown = gas_stove.get_cost_breakdown()
    ev_breakdown = ev.get_cost_breakdown(scenario)
    
    print(f"{'Metric':<20} {'Heat Pump':<10} {'Elec Cook':<10} {'Gas Stove':<10} {'EV':<12}")
    print("-" * 90)
    print(f"{'Base Cost':<20} ${hp_breakdown['base_cost']:>6,.0f}    ${electric_cooking_breakdown['base_cost']:>6,.0f}    ${gas_breakdown['base_cost']:>6,.0f}    ${ev_breakdown['base_cost']:>8,.0f}")
    print(f"{'Incentives':<20} ${hp_breakdown['total_incentives']:>6,.0f}    ${electric_cooking_breakdown['total_incentives']:>6,.0f}    ${0:>6,.0f}    ${ev_breakdown['total_incentives']:>8,.0f}")
    print(f"{'Net Cost':<20} ${hp_breakdown['net_cost']:>6,.0f}    ${electric_cooking_breakdown['net_cost']:>6,.0f}    ${gas_breakdown['net_cost']:>6,.0f}    ${ev_breakdown['net_cost']:>8,.0f}")
    print(f"{'Lifetime (years)':<20} {hp_breakdown['lifetime_years']:>7}    {electric_cooking_breakdown['lifetime_years']:>7}    {gas_breakdown['lifetime_years']:>7}    {ev_breakdown['lifetime_years']:>9}")
    print(f"{'Annual Cost':<20} ${hp_breakdown['cost_per_year']:>6,.0f}    ${electric_cooking_breakdown['cost_per_year']:>6,.0f}    ${gas_breakdown['annual_cost']:>6,.0f}    ${ev_breakdown['cost_per_year']:>8,.0f}")
    
    # EV total cost of ownership
    ev_tco = ev.get_total_cost_of_ownership()
    print(f"\nElectric Vehicle Total Cost of Ownership:")
    print(f"  Net purchase cost: ${ev_tco['net_purchase_cost']:,.0f}")
    print(f"  Total savings over {ev_tco['lifetime_years']} years: ${ev_tco['total_savings_over_lifetime']:,.0f}")
    print(f"  Net TCO: ${ev_tco['net_total_cost_of_ownership']:,.0f}")
    print(f"  Payback period: {ev_tco['payback_period_years']:.1f} years")


def demonstrate_electric_water_heating():
    """Quick demonstration of ElectricWaterHeatingAppliance usage."""
    print("\n" + "=" * 60)
    print("ELECTRIC WATER HEATING APPLIANCE (QUICK DEMO)")
    print("=" * 60)
    
    water_heater = ElectricWaterHeatingAppliance()
    breakdown = water_heater.get_cost_breakdown(IncentiveScenario.FULL_INCENTIVES)
    
    print(f"Appliance: {breakdown['appliance_type']}")
    print(f"Heater Type: {breakdown['heater_type']}")
    print(f"Capacity: {breakdown['capacity_gallons']} gallons")
    print(f"Base Cost: ${breakdown['base_cost']:,.2f}")
    print(f"Total Incentives: ${breakdown['total_incentives']:,.2f}")
    print(f"Net Cost: ${breakdown['net_cost']:,.2f}")
    print(f"Annual Cost: ${breakdown['cost_per_year']:,.2f}")
    
    # Show operating cost comparison
    operating_costs = water_heater.get_operating_cost_estimate()
    print(f"\nOperating Cost Comparison:")
    print(f"Gas Water Heater Annual Cost: ${operating_costs['gas_annual_cost']:,.2f}")
    print(f"Heat Pump Annual Cost: ${operating_costs['heat_pump_annual_cost']:,.2f}")
    print(f"Annual Savings: ${operating_costs['annual_savings']:,.2f}")


if __name__ == "__main__":
    demonstrate_electric_heating()
    demonstrate_electric_cooking()
    demonstrate_electric_water_heating()
    demonstrate_electric_vehicle()
    demonstrate_gas_stove()
    compare_cooking_options()
    compare_all_appliances()