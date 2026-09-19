# SAM integration review and parallel experiment

SAM works locally through PySAM. The earlier implementation had specific API and
time-alignment errors. Correcting those errors changes PV yield and system sizing.
However, replacing the simulator alone does not fix the research optimizer's
difference between marginal export revenue and realized Net Billing Tariff bills.

This review uses repository HEAD `280a4c735b0d4bed2154d201259d39495b04f5f2`.
It leaves the production pipeline and the existing figure edits unchanged.
The prototype is `experiments/sam_parallel.py`; tests are in
`tests/sam_parallel_test.py`. All model results are generated locally from existing
county files. No research profiles were submitted to REopt or another web service.

## Recommendation and explicit comparison

Retain the custom joint sizing and dispatch optimizer, but fix its economic
objective before using its selected sizes as minimum-cost research results.
Use SAM PVWatts through PySAM for PV generation. Use the detailed SAM battery
to check dispatch feasibility and calibrate the optimizer's battery constraints.
This combination fits the research better than replacing the optimizer with
SAM's built-in dispatch. Neither current path is ready to establish minimum
realized household cost without further work.

SAM is not one competing algorithm. Its PV model, battery simulation, dispatch
controller, and financial models serve different purposes. PySAM exposes the
simulation modules in Python. The desktop is another interface to SSC, the
SAM Simulation Core. See the [official SDK overview](https://sam.nlr.gov/software-development-kit-sdk.html).

| Question | Current custom implementation | SAM path tested here | Judgment |
|---|---|---|---|
| What produces PV energy? | Horizontal irradiance, a fixed performance ratio, and a simple temperature correction. | PVWatts uses solar geometry, direct/diffuse irradiance, orientation, temperature, and inverter behavior. | The custom model has less physical detail. Prefer PVWatts with documented roof assumptions. A default roof is not a measured roof. |
| What selects installed capacities? | One mixed-integer linear program jointly selects PV, battery energy, battery power, and hourly flows. | The prototype searches a finite capacity grid around SAM dispatch simulations. SAM's dispatch setting alone does not select capacities. | The custom formulation is better suited to joint research optimization. The tested SAM search cannot establish a global sizing optimum. |
| What economic quantity is minimized? | Capital plus hourly imports minus the full face value of hourly export credits. | SAM retail-rate dispatch receives hourly prices; the outer search ranks realized research bills. | The custom objective has a demonstrated ranking error against its own billing ledger. SAM's dispatch objective also lacks that complete ledger. Neither is an exact solution to the intended bill problem. |
| Can the battery follow the schedule? | Constant efficiency and simplified energy/power limits define feasibility. | Detailed battery simulation includes voltage, resistance, temperature, and capacity fade. | The custom battery is more idealized. SAM is a stronger physical check when its cell and converter parameters represent the intended product. |
| Does dispatch require future knowledge? | Annual optimization knows the entire input year. | Forecast assumptions depend on the selected SAM mode; native dispatch is not automatically a realistic controller. | Perfect foresight is valid for an explicitly stated ideal planning benchmark. It does not establish achievable household operation. |
| Why did the old API path fail? | Not an inherent limitation of custom optimization. | Earlier adapters mixed module APIs, misassigned settings, and mismatched weather values with timestamps. | These are integration defects. They do not show that SAM cannot simulate the research system. |

The most serious demonstrated issue is economic correctness. Battery physics
and PV assumptions also matter, but their measured cost effects are smaller
in these examples. That ordering is evidence from these cases, not a statewide
sensitivity result.

### The logical error in the cost objective

The optimizer treats earned export credit as realized savings. The research
billing ledger applies credit eligibility, balances, and settlement rules.
Those operations are not equivalent to subtracting every credit dollar from
annual cost.

For a simplified illustration, suppose a settlement permits $100 of eligible
charges to be offset. A system earns $150 of credits. Assume excess credits
expire without a payment. Another $10 of credits reduces the proxy objective
by $10, but reduces the bill by $0. An optimizer using that proxy can buy
additional PV or storage for savings that cannot be realized. This illustration
explains one mechanism. It is not a statewide California rule. PG&E's NBT
explicitly carries remaining base credits into the next annual period.

### Credit treatment differs by utility and credit type

The September 9, 2026 source check distinguishes base Energy Export Credits
(EEC), the ACC Plus bonus, and Net Surplus Compensation (NSC). NSC compensates
annual net-surplus energy in kWh at its specified rate. It is not a cash-out
of the full dollar balance of hourly export credits.

| Provider and program | Treatment of remaining base EEC at annual settlement | Source |
|---|---|---|
| PG&E NBT, bundled service | After applicable offsets and the net-surplus adjustment, remaining generation/delivery credits carry into the next Relevant Period while service remains on NBT. | [Schedule NBT, Special Conditions 2.e and 2.h, sheets 17-18](https://www.pge.com/tariffs/assets/pdf/tariffbook/ELEC_SCHEDS_NBT.pdf) |
| SCE NBT, bundled service | Remaining credits first offset the EEC adjustment, then eligible charges previously incurred during the Relevant Period. The residual is forfeited. | [Schedule NBT, Special Condition 4.e, sheet 23](https://www.sce.com/sites/default/files/custom-files/PDF_Files/ELECTRIC_SCHEDULES_NBT.pdf) |
| SDG&E NBT | The archived tariff sets excess base credits to zero at true-up after the applicable net-surplus debit. | `data/tariffs/sources/nbt_rules/sdge/2026-08-10/ELECTRIC_SCHEDULE_NBT.pdf`, Special Condition 3.f, sheet 8. The live tariff endpoint could not be retrieved during this check. |

PG&E and SCE separately preserve unused ACC Plus credits under their tariff
provisions. Do not apply the base-credit forfeiture rule to that bonus. See
PG&E Special Condition 2.h, sheet 19, and SCE Special Condition 4.e.iii, sheet 23.
NSC and credits for actual overpayments also need separate accounting.

These are not all California utilities or customer arrangements. Small
investor-owned utilities have separately approved programs, as described by the
[CPUC](https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/demand-side-management/customer-generation/net-energy-metering-and-net-billing).
LADWP's own NEM rider carries its credit balance to subsequent bills, subject
to charge exclusions, and clears a remaining balance at service termination.
See [LADWP's rider, Billing 3.c](https://www.ladwp.com/account/customer-service/electric-rates/ev-nem-reo-rates).
Community Choice Aggregator generation settlement must also be checked separately
from utility delivery settlement. PG&E and SCE tariffs explicitly distinguish
those services.

The prototype only models bundled service. Its `los-angeles` case uses a county
load/weather profile with SCE TOU-D-PRIME. It does not model LADWP or establish
the tariff for every Los Angeles household.

The code already distinguishes PG&E carryover from SCE and SDG&E forfeiture in
`TrueUpPolicy.for_utility`. However, a one-year bill does not value a surviving
credit bank's possible future use. The current prototype starts with zero
credit banks and does not pass ending balances into another billing year.
For PG&E lifetime economics, add multi-year credit accounting or a justified
value for the final credit balance. Unused this year does not mean expired or
worthless. The `unused_credit` diagnostic alone cannot establish lifetime loss.

The actual Los Angeles sensitivity provides a stronger counterexample. Both
rows below use the same SAM PV series, ideal battery model, capital assumptions,
and research dispatch optimizer. Only the capacity choice changes.

| Design | PV, kW DC | Battery, nominal kWh | Optimizer objective, USD/year | Research bill plus annualized capital, USD/year |
|---|---:|---:|---:|---:|
| Joint optimizer's selected design | 4.901 | 32.930 | 412.58 | 1,822.96 |
| Smaller feasible design, with dispatch solved at fixed capacities | 3.268 | 10.012 | 783.30 | 1,281.53 |

The optimizer prefers the first row. The second row costs $541.43 less per year
under the research billing calculation. This establishes that the selected
design does not minimize that realized cost. It does not establish that the
smaller design is the global optimum.

Rebilling the saved hourly profiles reproduces both annual bills. The difference
between each design's reported cost and optimizer objective reconciles as follows:

| Objective-to-bill adjustment, USD/year | Selected larger design | Smaller fixed-size design |
|---|---:|---:|
| Identical fixed charges | 289.81 | 289.81 |
| Base EEC forfeited by the modeled SCE ledger | 1,016.36 | 208.42 |
| Net-surplus EEC adjustment minus NSC | 104.20 | 0.00 |
| Total difference, using unrounded components | 1,410.37 | 498.23 |

The larger case earns $1,441.60 of base EEC and uses $425.24 for eligible
offsets, including the EEC adjustment. It forfeits the remaining $1,016.36.
It has 2,498.88 kWh of annual net surplus. The ledger debits $146.61 at the
specified adjustment rate and adds $42.41 of NSC. The smaller case is an
annual net importer, yet still forfeits $208.42 of generation credit because
generation and delivery credits have different eligible offsets. Both cases
use all earned ACC Plus credits. These are model diagnostics with archived
August 2026 rates, not actual customer bills or a complete independent tariff
certification. They establish an internal economic mismatch without relying
on an assumption that all California credits expire.

Recalculating the bill after optimization reports the discrepancy but leaves
the capacity and dispatch decisions unchanged. A solver's optimality guarantee
applies to its supplied objective, not to a different cost calculated afterward.
Fixed charges that are identical across designs shift both costs equally.
They cannot explain a reversed ranking; the design-dependent settlement gap can.
The research ledger itself still needs validation against the intended tariff.

### What the SAM comparison can establish

SAM has configurable net-billing, credit-carryover, true-up, and expiry options.
Its documentation also warns that some utility rate features may not be
representable. See [SAM electricity-rate documentation](https://samrepo.nlr.gov/help/electricity_rates.html).
The prototype uses `ur_metering_option=2`, ordinary net billing, and aggregated
hourly buy/sell signals. It does not configure complete California settlement
inside SAM. This is a limitation of the tested configuration. This review has
not established that every missing feature is impossible to implement in SAM.
Entering hourly NBT export prices alone does not establish NBT billing parity.

| Comparison | Supported conclusion | Unsupported conclusion |
|---|---|---|
| Replace current PV with SAM PV and hold the optimizer fixed | The effect of the specified PV-model and roof-assumption change | A validated minimum-cost NBT system |
| Replay custom dispatch through the detailed SAM battery | Feasibility and energy/cost effects under the selected battery parameters | Optimal dispatch for that detailed battery |
| Score custom and native SAM flows with the same research ledger | Which tested schedules/designs have lower cost under that common ledger | Independent confirmation that the ledger matches every utility bill |
| Native SAM size search | Best evaluable candidate under the stated search and dispatch assumptions | An exact comparison between two optimizers minimizing the full same NBT settlement |

A complete economic benchmark must first validate the shared settlement model
against utility tariff examples or bills. It must match service provider,
interconnection vintage, credit type, billing-cycle boundaries, true-up dates,
net-surplus adjustment, and inter-year carryover. It must then compare decisions
under that same objective and equivalent physical/forecast assumptions. Until
then, the native SAM results are a diagnostic benchmark, not a validated
replacement for the research optimizer.

### Fixes in priority order

1. **Align optimization with the realized research bill.** Represent credit
   balances, eligible offsets, non-bypassable charges, and settlement rules in
   the optimization where feasible. Verify the resulting objective against the
   independent bill calculator. Test cases where additional credits cannot
   reduce the bill. Both capacity selection and dispatch must use the intended
   economic value. A finite search scored by actual bills is a useful interim
   benchmark, but it must not claim a global optimum or exact dispatch.
   Validate the reference ledger first. Preserve surviving credits across
   years where the applicable tariff requires it.
2. **Make the SAM PV input contract explicit.** Keep weather timestamps and
   irradiance together during solar simulation. Convert output to the research
   time basis once. Define DC nameplate kW, AC power limits, nominal battery
   kWh, usable capacity, and interval duration. Pin the tested PySAM/SSC version
   and reject missing tariff or weather data.
3. **Calibrate the battery approximation.** Replay schedules through a specified
   SAM battery configuration. Measure delivered energy, power shortfalls,
   end-of-year SOC, capacity fade, and realized cost. Update efficiency, usable
   capacity, power limits, degradation, and replacement assumptions where the
   comparison supports a change. Default SAM cell parameters are not a product
   validation. Keep initial and final energy treatment equivalent.
4. **Separate planning potential from operational performance.** Retain perfect
   foresight as a clearly labeled ideal benchmark. Add a rolling dispatch
   evaluation with limited forecasts before making operational savings claims.
5. **Validate the comparison across the research scenarios.** Include positive
   storage, exhausted credit balances, different utilities, and roof assumptions.
   Resolve missing PG&E true-up inputs before ranking those candidates. Two
   counties and a low-cost sensitivity do not establish a statewide conclusion.

The proposed production path is: validated weather, SAM PV generation, corrected
custom joint optimization, independent research billing, and SAM battery replay.
If replay materially changes savings or feasible operation, tighten the custom
battery constraints and repeat optimization. Simply replacing the final bill
with a replay result does not restore optimal sizing.

## Results that answer the research question

The default comparison uses `baseline_coopt`, single-family detached homes,
8,760 hourly intervals, 2026 NBT prices, and the repository's August 9, 2026 import
tariff snapshot. Capital costs are $3,300/kW PV and $1,460.64/kWh battery.
The real discount rate is 7%. PV life and the analysis horizon are 25 years.
Battery replacement at year 15 follows `evaluations.eac.alpha_batt_npv`.

The reported annual cost includes electricity and annualized PV/storage capital.
It excludes gas, vehicles, and appliance costs, which are constant within each
comparison. It is not a complete household electrification cost.

| County | PV calculation and dispatch | PV size, model kW | Battery, nominal kWh | Annual cost, USD |
|---|---|---:|---:|---:|
| Alameda | Current GHI model + research optimizer | 1.244 | 0 | 1,928.74 |
| Alameda | SAM PVWatts + same optimizer | 1.169 | 0 | 1,885.23 |
| Los Angeles | Current GHI model + research optimizer | 1.149 | 0 | 1,995.63 |
| Los Angeles | SAM PVWatts + same optimizer | 1.087 | 0 | 1,957.82 |

SAM reduces annual cost by $43.50 in Alameda and $37.80 in Los Angeles in these
cases. Both versions choose zero storage at current costs. The tested SAM native
size search selects the same zero-storage designs because its candidate set
includes the continuous optimizer's selected pair. This agreement does not test
positive-storage dispatch or establish a statewide result.

PVWatts defines size as DC nameplate kW. The current helper calls its output AC
energy but uses a simplified capacity multiplier. Its documentation sometimes
calls the size AC kW. The table preserves the current size variable and uses the
same capital cost per kW. Resolve that inconsistent capacity terminology before
publication; this experiment does not establish a calibrated physical AC rating
for the simplified model.

| County | Current yield, kWh/model kW | Correct SAM yield, kWh/kW DC | SAM with old irradiance-only shift, kWh/kW DC |
|---|---:|---:|---:|
| Alameda | 1,446.83 | 1,648.86 | 343.47 |
| Los Angeles | 1,476.43 | 1,678.42 | 339.46 |

SAM produces about 14% more annual energy per unit of modeled capacity here.
It uses direct and diffuse irradiance, solar geometry, roof tilt, module
temperature, and an inverter. The current model uses horizontal irradiance,
a fixed performance ratio of 0.80, and a simple temperature correction.
The prototype uses a south-facing roof at 20 degrees, 14% losses, a 1.2 DC/AC
ratio, and 96% inverter efficiency. The yield change therefore represents a
specified model-and-assumption change, not proof that the current yield is wrong
for every rooftop.

For a positive-storage comparison, the Los Angeles sensitivity sets PV capital
cost to $2,000/kW and battery capital cost to $200/kWh. These are experimental
assumptions, not market-price estimates. Other financial and tariff assumptions
stay the same.

| Method | PV, model kW | Battery, nominal kWh | Annual cost, USD |
|---|---:|---:|---:|
| Current PV + research sizing/dispatch | 5.572 | 34.013 | 1,960.56 |
| SAM PV + research sizing/dispatch | 4.901 | 32.930 | 1,822.96 |
| Same SAM-PV design and requested dispatch replayed through detailed SAM battery | 4.901 | 32.945 | 1,833.43 |
| Best tested SAM native dispatch/size candidate | 3.268 | 10.012 | 1,354.25 |
| Research dispatch at that smaller candidate's capacities, using SAM PV | 3.268 | 10.012 | 1,281.53 |

The detailed battery delivers 5,389.58 kWh, compared with the requested ideal
dispatch's 5,839.90 kWh. Its summed absolute hourly dispatch deviation is
804.11 kWh across charging and discharging. Realized annual cost rises $10.47.
Cell-count rounding accounts for the small nominal-capacity increase. SAM also
models voltage, resistance, thermal effects, and first-year capacity fade.
Matching converter efficiencies does not remove these physical differences.

The larger economic difference comes from the objective. At the 4.901 kW,
32.930 kWh design, the research objective is $412.58/year, while the realized
bill plus capital is $1,822.96/year. At the smaller 3.268 kW, 10.012 kWh design,
the same research dispatch model has a higher objective, $783.30/year, but a
lower realized cost, $1,281.53/year. Thus the marginal objective prefers the
larger design even though the authoritative billing calculation favors the
smaller tested design. Identical fixed charges explain a constant part of the
objective-to-bill gap; they do not change which design is cheaper. Unused export
credits and the ledger's settlement rules make the gap change with size.
This reproduces the limitation already documented in
`docs/NBT_TARIFF_MODEL.md`.

The last row is a fixed-size diagnostic, not another continuous sizing optimum.
The SAM native row is the best member of a finite candidate set, not a proven
global optimum. It uses first-year operation from 20% SOC and does not impose
the research optimizer's cyclic annual SOC constraint. The reported positive-
storage examples end approximately at 20% SOC. All candidates record final SOC.

## What failed in earlier iterations

1. **The simplified and detailed battery APIs were mixed.**
   `notebooks/sam_dispatch_optimization.ipynb` imports `PySAM.Battwatts`, then
   accesses `BatteryDispatch.batt_dispatch_choice`. A direct execution reproduces
   `AttributeError`: `Battwatts` has no `BatteryDispatch` group. The local SAM
   PVWatts-Battery screen offers peak shaving and custom dispatch only. Its
   simplified battery is not the detailed `PySAM.Battery` model. See the separate
   [Battwatts API](https://nrel-pysam.readthedocs.io/en/v6.0.1/modules/Battwatts.html)
   and [Battery API](https://nrel-pysam.readthedocs.io/en/v6.0.1/modules/Battery.html).

2. **Several settings used the wrong group or dispatch enumeration.**
   SOC bounds belong to `BatteryCell` in PySAM, even though SAM displays them on
   its dispatch page. A direct assignment to `BatteryDispatch.batt_minimum_SOC`
   fails. The detailed module's custom hourly power target uses dispatch choice
   `2`; choice `3` is a manual month/hour schedule. The old custom-dispatch
   notebook recommends choice `3` with `batt_custom_dispatch`. That combination
   does not select the intended hourly target. These distinctions are tested.

3. **Weather values were shifted without their solar-time coordinates.**
   The deleted `step9_run_sam_model_for_solar_storage.py`, inspected at
   `21229a8^`, rolls irradiance and meteorological arrays eight hours left while
   retaining their time coordinates and UTC offset. SAM then combines daylight
   irradiance with the wrong sun position. The table above isolates that mistake
   with the same PVWatts settings. The corrected adapter runs PVWatts with the
   original UTC weather, then rolls its AC generation output to PST once.
   [SAM time conventions](https://natlabrockies.github.io/SAM/doc/weather-data/weather_time_convention.html)
   explain how the timestamp and minute field affect solar position.

4. **Exported input files and modules were not consistently matched.**
   `notebooks/00_explore_sam_from_configuration.ipynb` preserves an unknown-input
   `AttributeError`, followed by `pvsamv1 execution error: No weather data supplied`.
   Several notebooks reference `SAM_configuration/`, which is absent in the
   current checkout. The surviving `SAM_Detailed_PV_Battery/` exports belong to
   a different detailed-PV chain. These are recorded failures and missing-file
   evidence; not every historical notebook failure was reconstructed.
   Use matching per-module PySAM JSON exports, exclude the `number_inputs`
   metadata field, and supply weather explicitly. Follow the
   [SAM input-export workflow](https://nrel-pysam.readthedocs.io/en/main/inputs-from-sam.html).

5. **The runtime versions differ materially.**
   Homebrew Python 3.11 has PySAM 6.0.1 / SSC 298. The checked repository virtual
   environment and system Python lack that distribution. The installed desktop
   is SAM 2025.4.16. The isolated comparison environment uses PySAM 7.1.1.post1 /
   SSC 306. SSC 302 added battery exports for retail-rate dispatch; SSC 298 cannot
   represent that strategy just by setting an export flag. Fixed-size candidate
   bills differ by as much as $114/year between the tested PySAM versions.
   That comparison also includes changed cell defaults and sizing round-off;
   it does not isolate the export feature alone. See the
   [official release notes](https://natlabrockies.github.io/SAM/doc/releasenotes.html).

6. **Dispatch and joint sizing were treated as the same operation.**
   Selecting peak shaving, self-consumption, or retail-rate dispatch does not
   itself optimize PV and battery capacities. The earlier pipeline separately
   sized PV and used configured storage. The current research MILP jointly
   selects PV, battery energy, battery power, and hourly flows. SAM supports
   outer searches through [parametric runs and scripting](https://natlabrockies.github.io/SAM/doc/simulation-options/optimization.html).
   Its REopt button invokes another optimization service.

7. **Default assumptions and exceptions hid differences.**
   Older code contains broad exception handlers, guessed tariff values, fixed
   batteries, mismatched array lengths, and missing-input fallbacks. The saved
   custom-dispatch notebook includes a 168-versus-336 plotting error. A 1-hour
   average power of 1 kW is numerically 1 kWh over that interval; annual sums
   cannot distinguish those units. The prototype rejects incomplete/non-finite
   hourly data and records the exact data hashes. It uses fresh SAM objects per
   candidate because `from_existing` shares SSC data rather than cloning it.

## Local SAM and registration status

The browser was used to inspect the official SAM download and registration
instructions. Those instructions request or resend software keys through the
desktop registration window. The website's Register link creates a forum
account; it is not the software-key form.
[Registration instructions](https://sam.nlr.gov/forum/forum-general/1046-registering-sam.html).

The installed app already contains an email and registration key, but displays
“The registration key could not be verified.” Its Welcome page also fails to
load online content. The installed `webapis.conf` still points registration at
`developer.nrel.gov`. The April 2026 maintenance update changed API URLs to
`nlr.gov`. That makes an outdated endpoint a plausible explanation for the
desktop connectivity problem, but this review has not established the network
failure's exact cause. A replacement key alone may not resolve it.

Automatic approval review blocked submitting the configured Berkeley email to
SAM/NLR. Approval for that specific email and destination was requested. A new
key has not been requested, received, or installed. No registration secret is
stored in this report or the prototype.

Using the app's normal “Skip for now” option, the local Phoenix PVWatts-Battery
example simulated successfully. Its system-design inputs, dispatch choices,
REopt control, and Shift+F5 export dialog were inspected. The example uses
default Phoenix inputs; it is not a research comparison result. The export
dialog provides PySAM JSON, general JSON, LK, C, MATLAB, Java, C#, and VBA.

The PySAM county simulations completed with desktop registration unresolved.
Local SSC execution, SAM desktop registration, weather-download credentials,
and the remote REopt API are separate dependencies.

## Integration that fits this research

Use SAM as a local physical simulation layer and retain the research's explicit
household, tariff, and annualization definitions. The
[SAM SDK](https://sam.nlr.gov/software-development-kit-sdk.html) exposes SSC;
PySAM provides Python modules around those calculations. `Pvwattsv8` supplies
PV generation. `Battery` supplies detailed storage behavior. `Utilityrate5` and
`Cashloan` offer SAM billing and residential financial models, but their default
assumptions are not substitutes for the current California research ledger.

The prototype implements three useful integration paths:

- `sam_pv_milp`: replace only the PV yield input to the current joint optimizer.
  This is the smallest production integration and isolates the PV-model effect.
- `sam_battery_replay`: pass the selected AC battery-power schedule to detailed
  SAM mode `2`. This checks physical realizability; it does not re-optimize the
  detailed battery's dispatch.
- `sam_native_*`: enumerate PV and storage capacities, use detailed SAM mode `4`
  for dispatch, and rank each supported result using the research's realized
  NBT bill plus annualized capital. This is a working finite co-sizing prototype.

The native search uses PV annual-generation fractions of 0, 0.5, 1, and 1.5
times load, and nominal battery requests of 0, 5, 10, 20, and 40 kWh by default.
It also evaluates the paired capacities from `sam_pv_milp`. Battery AC power is
fixed at 1 kW per requested nominal kWh for these candidates. It does not search
battery power independently. Both research and native paths disable grid
charging. They allow PV-origin battery exports where the model supports them.

`BatteryTools.battery_model_sizing` updates cell counts, current limits, mass,
and thermal area together. The prototype explicitly selects DC nominal energy
as the sizing/cost basis and AC power as the converter limit. A nominal 10 kWh
battery with 20–90% SOC has approximately 7 kWh available before physical
losses and capacity fade. The reported installed capacity includes cell-count
rounding. In SAM profile exports, `Battery SOC` is nominal capacity multiplied
by SOC fraction for schema compatibility; it is not a measured electrochemical
energy inventory. Detailed initial/final SOC percentages are in `metrics.json`.
Cell rounding can put an actual 40 kWh candidate slightly above 40 kWh. The
research optimizer's 40 kWh bound is exact; compare those upper-bound cases
with that distinction in mind.

The same normalized hourly buy/sell prices feed both optimizers. SAM uses these
as price signals under its net-billing dispatch option. The external research
ledger remains authoritative for component credit banks, fixed charges,
non-bypassable charges, and true-up. Native SAM dispatch does not implement that
entire ledger objective. See [SAM dispatch documentation](https://natlabrockies.github.io/SAM/doc/battery-storage/battery_dispatch_btm.html).

REopt is an alternative joint-sizing engine, accessed remotely through a job
submission and results-polling API. The SAM/PySAM helpers map SAM inputs to its
schema. The GUI can import returned sizing and dispatch. Before using it for
headline results, verify that the adapter transmits the complete hourly export
prices, equivalent costs/incentives, battery constraints, and the intended tariff
settlement. Do not equate a successful job response with an equivalent research
objective. The [Battery API's REopt helper](https://nrel-pysam.readthedocs.io/en/v6.0.1/modules/Battery.html#PySAM.Battery.Battery.Reopt_size_standalone_battery_post)
describes the module mapping. This review does not claim a validated REopt run.

## Running and reviewing the prototype

The temporary environment created for this review is
`/private/tmp/sam-parallel-venv`. It inherits the existing Homebrew scientific
packages and contains a separate PySAM 7.1.1.post1 installation. The existing
PySAM 6.0.1 installation remains unchanged. PyPI did not offer a compatible
8.0.0 wheel during this run, despite the main documentation showing version 8.

From the repository root, use a new output directory for each run:

```bash
/private/tmp/sam-parallel-venv/bin/python -m experiments.sam_parallel \
  --counties alameda los-angeles \
  --output analysis_results/sam_parallel_review
```

Reproduce the positive-storage sensitivity:

```bash
/private/tmp/sam-parallel-venv/bin/python -m experiments.sam_parallel \
  --counties los-angeles --pv-cost 2000 --battery-cost 200 \
  --pv-load-fractions 0 .5 1 1.5 --battery-sizes 0 10 20 40 \
  --output analysis_results/sam_parallel_low_cost_review
```

To recreate the environment on this computer:

```bash
/opt/homebrew/bin/python3.11 -m venv --system-site-packages /private/tmp/sam-parallel-venv
/private/tmp/sam-parallel-venv/bin/python -m pip install 'NREL-PySAM==7.1.1.post1'
```

This setup assumes the existing research dependencies are installed in Homebrew
Python. It is not a complete dependency lock for a new computer. The prototype
checks the requested PySAM version at startup. To reproduce the older runtime
comparison, use Homebrew Python and `--expected-pysam 6.0.1` explicitly.

Completed outputs:

- `analysis_results/sam_parallel/comparison.csv`: installed PySAM 6.0.1 baseline.
- `analysis_results/sam_parallel_pysam7/comparison.csv`: corrected runtime baseline.
- `analysis_results/sam_parallel_low_cost/comparison.csv`: positive-storage sensitivity.
- Each run's `manifest.json`: HEAD, versions, arguments, and code/tariff hashes.
- Each county's `inputs.json` and `inputs_hourly.csv`: input hashes, calendar
  mapping, aligned load, PV yields, and prices.
- Each county's `native_search.json`: best evaluable candidate and unavailable
  bill count. Six Alameda candidates lack the required PG&E true-up source.
- Each case's `metrics.json` and Step 9-compatible dispatch/export CSVs.

The final code also audits the realized bill at a positive-storage native
winner's capacities using research dispatch. This audit was added after the
initial sensitivity finished, then run separately against its saved inputs.
`native_size_audit_provenance.json` records that supplementary execution.

The CSV schema permits comparison and downstream adapters without changing the
main pipeline. Output folders include case names, so the existing pipeline does
not automatically discover them. To integrate after review, explicitly route
the selected case's dispatch/export files to a separate scenario and use the
matching capacity metrics for capital accounting. Do not replace production
dispatch while retaining capacities from another run.

Validation: 58 focused tests passed; one existing test was skipped. These cover
the new adapter, production co-optimization, and dispatch invariants. The new
tests check malformed hours, timezones, duplicate timestamps, zero storage,
custom-dispatch sign/units, native high-price battery exports, and explicit
unavailable bills. All completed comparison cases pass AC flow balance and
meter-direction checks; the maximum AC balance residual is below 0.000005 kWh
per interval. The full electrification pipeline and full repository suite were
not rerun because this change only adds an isolated experiment.

## Follow-up work requiring separate review

1. Complete the pending registration request and verify the desktop key. Update
   the desktop's official maintenance release if connectivity still fails.
2. Define one documented DC/AC capacity convention and one standard-time contract.
3. Calibrate roof orientation, shading, losses, and battery technology assumptions.
   The SAM default cell model is an example, not a validated Powerwall model.
4. Optimize the realized tariff ledger, or explicitly evaluate and refine candidate
   sizes against it. The sensitivity shows this can change the economic conclusion.
5. Supply the missing PG&E surplus true-up source before ranking all candidates.
6. Expand native sizing resolution and battery power choices. Check annual boundary
   conditions and lifetime degradation before treating it as a replacement optimizer.
7. Validate REopt input/output and settlement equivalence separately if remote
   optimization is still desired.

No production fixes or commits were included. These files constitute one review
unit under the repository's change-management rules.
