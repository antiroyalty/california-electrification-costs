"""Matched credit cases must preserve household comparisons and saved accounting."""
from dataclasses import asdict, replace
import json
from math import fsum

import pandas as pd
import pytest

from appliances.federal_credits import FEDERAL_ITC_25D
from evaluations.eac import compute_eac_from_inputs
from evaluations.federal_credits import (
    FederalCreditCase, HouseholdCreditDeclaration, PVStorageCreditPolicy,
)
from figure_builder import electrification as comparison
from figure_builder.dispatch import HOUSING_TYPE
from figure_builder.federal_accounting import load_credit_declarations
from figure_builder.tests.test_electrification import _saved_runs


def _declare(case=FederalCreditCase.ALL, electric=True):
    return HouseholdCreditDeclaration(
        pv_storage_policy=PVStorageCreditPolicy(case, 1, 1),
        space_heat_pump_eligible_basis_usd=12000 if electric else 0,
        water_heat_pump_eligible_basis_usd=4000 if electric else 0,
        heat_pump_realization_fraction=1,
        eligible_vehicle_credit_usd=7500 if electric else 0,
        vehicle_realization_fraction=1, vehicle_receipt_year=0,
    )


def _federal_runs(tmp_path, case=FederalCreditCase.ALL):
    args = _saved_runs(tmp_path, ("alameda",))
    base = args['base_input_dir']
    declarations = []
    for household, scenario in comparison.HOUSEHOLDS.items():
        electric = household == 'electric'
        declaration = _declare(case, electric)
        row = asdict(declaration)
        row['pv_storage_policy']['case'] = case.value
        declarations.append(dict(scenario=scenario, county_slug='alameda', **row))
        suffix = f'{scenario}_{HOUSING_TYPE.replace("-", "_")}.csv'
        ledger_path = base / 'capital_costs' / f'capital_costs_{suffix}'
        ledger = pd.read_csv(ledger_path)
        if electric:
            ledger.loc[ledger.appliance_type == 'heating', ['base_cost', 'net_cost']] = [12000, 1000]
            ledger.loc[ledger.appliance_type == 'vehicle_charging', 'lifetime_years'] = 12
            water = dict(ledger.iloc[0])
            water.update(appliance_type='hot_water', base_cost=4000, net_cost=500)
            ledger = pd.concat([ledger, pd.DataFrame([water])], ignore_index=True)
        ledger.to_csv(ledger_path, index=False)
        # The new collector must not read rounded/mixed-incentive PV summaries.
        (base / 'capital_costs' / f'capital_costs_summary_with_pv_{suffix}').unlink()
        (args['completion_dir'] / scenario / 'alameda_diagnostics_gabc1234.html').unlink()
        directory = base / scenario / HOUSING_TYPE / 'alameda'
        assets_path = directory.parent / 'CAPITAL_COSTS/electrified_assets.csv'
        assets = pd.read_csv(assets_path)
        design = assets.iloc[0]
        pv_kw = 1.23456789 if electric else .623456789
        purchase = dict(pv=pv_kw*3300, storage=0)
        receipts = declaration.pv_storage_policy.receipts_for_system(
            pv_gross_usd=purchase['pv'], storage_gross_usd=0, storage_capacity_kwh=0,
        )
        report = compute_eac_from_inputs(
            None, dict(pv_capex=purchase['pv'], storage_capex=0),
            federal_credit_receipts=receipts, annual_bill_electric=600,
        )
        a = dict(
            schema_version=1, scope='solar_storage_only', scenario=scenario,
            county='alameda', housing_type=HOUSING_TYPE,
            cost_basis='gross_with_one_time_federal_credits',
            federal_credit_policy=row['pv_storage_policy'], federal_rule_25d=asdict(FEDERAL_ITC_25D),
            federal_credit_receipts=asdict(receipts),
            capital_assumptions=dict(discount_rate=.07, study_years=25, battery_life_years=15,
                                     pv_usd_per_kw=3300, battery_usd_per_kwh=1460.64, battery_usd_per_kw=0),
            capacities=dict(pv_kw=pv_kw, battery_kwh=0, battery_kw=0), purchase_costs_usd=purchase,
            annual_costs_usd=dict(capital=report.capex_pv, electricity_bill=600,
                                  degradation=0, total=report.total()),
            dispatch_assumptions=dict(allow_grid_charging=False, allow_battery_export=True,
                                      max_battery_kwh=40, battery_degradation_usd_per_kwh=0),
            tariff=dict(utility=design['Utility'], import_plan=design['Import Tariff Plan'],
                        import_source_id=design['Import Tariff Source ID'],
                        snapshot_date=design['Import Tariff Snapshot As Of'], billing_year=2026,
                        nbt_vintage=2026, customer_segment='standard', nbc_dollars_per_kwh_override=None),
        )
        (directory / 'coopt_accounting_alameda.json').write_text(json.dumps(a))
        solver = dict(options=dict(annual_cost_gap_usd=1), optimality_gap_usd=.25,
                      lower_bound_usd=report.total()-.25)
        (directory / 'coopt_solver_alameda.json').write_text(json.dumps(solver))
        for key, value in {'Solar Capacity (kW)': pv_kw, 'Battery Power Capacity (kW)': 0,
                           'Capital Cost Basis': a['cost_basis'], 'Federal Credit Case': case.value,
                           'Coopt Total Cost': round(report.total(), 4)}.items():
            assets[key] = value
        assets.to_csv(assets_path, index=False)
    path = tmp_path / 'credit_declarations.json'
    path.write_text(json.dumps(dict(schema_version=1, households=declarations)))
    args['federal_credit_declarations'] = path
    args['completion_dir'] = None
    return args


def _read_case(args, household='electric'):
    scenario = comparison.HOUSEHOLDS[household]
    directory = args['base_input_dir'] / scenario / HOUSING_TYPE / 'alameda'
    path = directory / 'coopt_accounting_alameda.json'
    return path, json.loads(path.read_text())


@pytest.mark.parametrize('case', list(FederalCreditCase))
def test_builds_all_four_federal_cells_with_itemized_receipts_and_source_hashes(tmp_path, case):
    args = _federal_runs(tmp_path, case)
    source = comparison.build_electrification_source(**args)
    costs = comparison.load_electrification_costs(source).set_index('case')
    assert set(costs.index) == set(comparison.CASES)
    assert (costs.federal_credit_case == case.value).all()
    electric = costs.loc[['electric_no_solar', 'electric_optimized']]
    assert electric.heat_pumps_25c_usd.tolist() == ([2000, 2000] if case is FederalCreditCase.ALL else [0, 0])
    assert electric.vehicle_30d_usd.tolist() == ([7500, 7500] if case is FederalCreditCase.ALL else [0, 0])
    assert (costs.loc[['gas_no_solar', 'gas_optimized'], ['heat_pumps_25c_usd', 'vehicle_30d_usd']] == 0).all().all()
    assert costs.loc['electric_no_solar', 'pv_25d_usd'] == 0
    assert costs.loc['electric_optimized', 'solar_kw'] == pytest.approx(1.23456789, abs=1e-12)
    assert costs.reporting_cost_difference_usd_per_year.abs().max() < 1e-6
    annuity = fsum(1.07**-year for year in range(1, 26))
    capital_before = 16000/fsum(1.07**-year for year in range(1, 16)) + 18000/fsum(1.07**-year for year in range(1, 13))
    annual_credit = (2000/1.07 + 7500)/annuity if case is FederalCreditCase.ALL else 0
    assert electric.capex_electric.tolist() == pytest.approx([capital_before-annual_credit]*2)
    manifest = json.loads(source.with_suffix('.manifest.json').read_text())
    assert manifest['cost_basis'] == 'gross_with_one_time_federal_credits'
    paths = [f['path'] for f in manifest['source_files']]
    assert sum('coopt_accounting' in path for path in paths) == 2
    assert sum('coopt_solver' in path for path in paths) == 2
    assert any('credit_declarations.json' in path for path in paths)
    assert not any('diagnostics' in path or 'summary_with_pv' in path for path in paths)


def test_appliance_credits_lower_electrification_cost_without_inventing_a_package_effect(tmp_path):
    frames = {}
    for case in (FederalCreditCase.PV_STORAGE, FederalCreditCase.ALL):
        args = _federal_runs(tmp_path / case.value, case)
        source = comparison.build_electrification_source(**args)
        frames[case] = pd.read_csv(source.with_suffix('.comparisons.csv')).iloc[0]
    solar, all_credits = frames.values()
    benefit = (2000/1.07+7500)/fsum(1.07**-year for year in range(1, 26))
    for column in ('electrification_savings_no_solar_usd_per_year',
                   'electrification_savings_optimized_usd_per_year'):
        assert all_credits[column]-solar[column] == pytest.approx(benefit)
    assert all_credits.package_effect_usd_per_year == pytest.approx(solar.package_effect_usd_per_year)
    assert all_credits.electric_adoption_savings_usd_per_year == pytest.approx(solar.electric_adoption_savings_usd_per_year)


@pytest.mark.parametrize('defect,message', [
    ('receipt', 'credit receipts'), ('price', 'PV purchase cost'), ('size', 'Solar Capacity'),
    ('year', '25-year study'), ('case', 'optimizer policy'), ('bill', 'reported electricity bill'),
    ('solver', 'solver bound'), ('missing', 'file not found'), ('rounding', 'Solar Capacity'),
    ('settings', 'Optimization settings differ'), ('heat_basis', 'eligible heating basis'),
    ('ev_in_gas', 'requires an electric vehicle'), ('missing_declaration', 'exactly cover'),
    ('duplicate_declaration', 'Duplicate household'), ('unknown_field', 'malformed household'),
])
def test_rejects_mismatched_or_incomplete_federal_inputs(tmp_path, defect, message):
    args = _federal_runs(tmp_path)
    path, a = _read_case(args)
    if defect in {'heat_basis', 'ev_in_gas', 'missing_declaration', 'duplicate_declaration', 'unknown_field'}:
        path = args['federal_credit_declarations']
        declarations = json.loads(path.read_text())
        if defect == 'heat_basis':
            declarations['households'][1]['space_heat_pump_eligible_basis_usd'] = 12001
        elif defect == 'ev_in_gas':
            declarations['households'][0]['eligible_vehicle_credit_usd'] = 7500
        elif defect == 'missing_declaration':
            declarations['households'].pop()
        elif defect == 'duplicate_declaration':
            declarations['households'].append(declarations['households'][0])
        else:
            declarations['households'][1]['ignored_parameter'] = 1
        path.write_text(json.dumps(declarations))
    elif defect == 'missing':
        path.unlink()
    elif defect == 'rounding':
        assets = path.parent.parent/'CAPITAL_COSTS/electrified_assets.csv'
        frame = pd.read_csv(assets)
        frame['Solar Capacity (kW)'] = frame['Solar Capacity (kW)'].round(2)
        frame.to_csv(assets, index=False)
    elif defect == 'solver':
        path = path.with_name('coopt_solver_alameda.json')
        solver = json.loads(path.read_text())
        solver['lower_bound_usd'] -= 1
        path.write_text(json.dumps(solver))
    elif defect == 'bill':
        bills = path.parent / 'results/electricity/RESULTS_electricity_annual_costs_alameda_20260915_11.csv'
        frame = pd.read_csv(bills)
        frame.loc[1, 'electricity.PG&E.E-ELEC_NEM3'] += 1
        frame.to_csv(bills, index=False)
    else:
        if defect == 'receipt': a['federal_credit_receipts']['amounts']['pv_25d_usd'] += 1
        elif defect == 'price': a['purchase_costs_usd']['pv'] += 1
        elif defect == 'size': a['capacities']['pv_kw'] += .001
        elif defect == 'year': a['capital_assumptions']['study_years'] = 20
        elif defect == 'case': a['federal_credit_policy']['case'] = 'no_federal_credits'
        elif defect == 'settings': a['tariff']['customer_segment'] = 'equity'
        path.write_text(json.dumps(a))
    with pytest.raises((ValueError, FileNotFoundError), match=message):
        comparison.build_electrification_source(**args)
    assert not args['source'].exists()


@pytest.mark.parametrize('field,value', [('heat_pump_realization_fraction', 1.1),
                                        ('vehicle_realization_fraction', float('nan')),
                                        ('vehicle_receipt_year', -1),
                                        ('eligible_vehicle_credit_usd', 7501)])
def test_invalid_household_declarations_fail(field, value):
    with pytest.raises(ValueError):
        replace(_declare(), **{field: value})


def test_partial_realization_applies_after_the_shared_heat_pump_cap():
    declaration = replace(_declare(), heat_pump_realization_fraction=.5,
                          vehicle_realization_fraction=.25, vehicle_receipt_year=2)
    receipts = declaration.receipts_for_system(pv_gross_usd=20000, storage_gross_usd=0,
                                              storage_capacity_kwh=0)
    assert receipts.amounts.heat_pumps_25c_usd == 1000
    assert receipts.amounts.vehicle_30d_usd == 1875
    assert receipts.home_receipt_year == 1 and receipts.vehicle_receipt_year == 2


def test_declaration_policy_must_match_between_households(tmp_path):
    args = _federal_runs(tmp_path)
    path = args['federal_credit_declarations']
    declarations = json.loads(path.read_text())
    declarations['households'][1]['pv_storage_policy']['realization_fraction'] = .5
    path.write_text(json.dumps(declarations))
    with pytest.raises(ValueError, match='same solar/storage credit policy'):
        load_credit_declarations(path, {(s, 'alameda') for s in comparison.HOUSEHOLDS.values()})


@pytest.mark.parametrize('defect,message', [
    ('no_receipts', 'require federal receipts'), ('no_solar', 'with_solar=True'),
    ('wrong_key', 'exactly cover'), ('missing_cost', 'missing storage_capex'),
    ('negative_cost', 'finite and nonnegative'),
])
def test_explicit_design_costs_require_a_complete_federal_reporting_context(tmp_path, defect, message):
    from helpers.plot_scenario_comparison_helper import collect_eac_components_by_county

    args = _federal_runs(tmp_path, FederalCreditCase.NONE)
    scenario = comparison.HOUSEHOLDS['electric']
    key = scenario, 'alameda'
    receipts = _declare(FederalCreditCase.NONE).receipts_for_system(
        pv_gross_usd=100, storage_gross_usd=0, storage_capacity_kwh=0,
    )
    options = dict(federal_credit_receipts_by_household={key: receipts},
                   pv_storage_costs_by_household={key: dict(pv_capex=100, storage_capex=0)})
    if defect == 'no_receipts': options['federal_credit_receipts_by_household'] = None
    elif defect == 'no_solar': options['with_solar'] = False
    elif defect == 'wrong_key': options['pv_storage_costs_by_household'] = {}
    elif defect == 'missing_cost': del options['pv_storage_costs_by_household'][key]['storage_capex']
    else: options['pv_storage_costs_by_household'][key]['pv_capex'] = -1
    with pytest.raises(ValueError, match=message):
        collect_eac_components_by_county(
            str(args['base_input_dir']), HOUSING_TYPE, [scenario], ['alameda'],
            timestamp=args['run_timestamps'][scenario], **options,
        )


def test_federal_cli_selects_the_dedicated_comparison_without_legacy_completion_pages(monkeypatch):
    from unittest.mock import patch
    import sys

    monkeypatch.setattr(sys, 'argv', [
        'electrification', '--model-run-sha', 'abc1234', '--gas-run-timestamp', '20260919_10',
        '--electric-run-timestamp', '20260919_11', '--base-input-dir', 'isolated-inputs',
        '--source', 'comparison.csv', '--counties', 'alameda',
        '--federal-credit-declarations', 'declarations.json',
    ])
    with patch.object(comparison, 'build_electrification_source') as build:
        comparison.main()
    assert build.call_args.kwargs['completion_dir'] is None
    assert build.call_args.kwargs['federal_credit_declarations'] == 'declarations.json'
    assert build.call_args.kwargs['counties'] == {'alameda'}


def test_all_credit_reporting_reuses_the_pv_credit_design_without_changing_saved_inputs(tmp_path):
    args = _federal_runs(tmp_path, FederalCreditCase.PV_STORAGE)
    path = args['federal_credit_declarations']
    original_accounting = {household: _read_case(args, household)[0].read_bytes()
                           for household in comparison.HOUSEHOLDS}
    declarations = json.loads(path.read_text())
    for declaration in declarations['households']:
        declaration['pv_storage_policy']['case'] = FederalCreditCase.ALL.value
    path.write_text(json.dumps(declarations))
    source = comparison.build_electrification_source(**args)
    costs = comparison.load_electrification_costs(source).set_index('case')
    assert (costs.federal_credit_case == FederalCreditCase.ALL.value).all()
    assert costs.loc['electric_optimized', 'heat_pumps_25c_usd'] == 2000
    assert costs.loc['electric_no_solar', 'vehicle_30d_usd'] == 7500
    for household, original in original_accounting.items():
        assert _read_case(args, household)[0].read_bytes() == original
