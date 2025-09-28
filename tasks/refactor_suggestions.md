# Refactoring `pvsamv1` main() for Readability and Correctness

This document proposes how to refactor the `main()` function used to run the PySAM `Pvsamv1` model (see `pvsamv1_battery.py`) so that it is easy and human‑readable, while ensuring supporting functions are clear, small, and correct.

The end state is a short, orchestration‑only `main()` that sequences explicit steps. All details live in small, testable helpers with clear inputs/outputs and minimal side effects.

## Goals

- Keep `main()` as a readable, top‑level script of what happens, in order.
- Isolate I/O (env, filesystem, printing/plotting) from computation and model interaction.
- Keep helpers small (≈10–30 lines), single‑purpose, and well‑named.
- Prefer pure functions for transforms; contain side effects to well‑defined boundaries.
- Improve correctness with type hints, dataclasses, precondition checks, and consistent logging.

## Core Principles

- Single responsibility: one reason to change per function.
- Descriptive naming: nouns for data, verbs for actions; snake_case.
- Explicit data flow: pass dependencies as parameters; no hidden globals.
- Defensive programming: validate lengths, ranges, and required keys early.
- Centralized error handling and logging; no deep try/except ladders in `main()`.
- PySAM‑aware invariants: SOC ∈ [0,100], 8760‑hour arrays by default, and PV AC flows sum correctly.

## Target Architecture

`main()` becomes a short, linear orchestrator. Supporting functions are grouped by responsibility:

- Configuration: read/validate env or CLI, construct a typed configuration.
- Presets I/O: read JSON, safely apply into modules, report failures clearly.
- Module lifecycle: create modules, enforce invariants (e.g., SOC bounds), confirm dispatch.
- Resource attachers: weather and load attachment with clear success/failure semantics.
- Execution: run model once dependencies are attached; handle/propagate errors cleanly.
- Extraction: read outputs into well‑typed arrays and data structures.
- Reporting: concise human summaries, tables, and optional plots.

## Orchestrator Skeleton (Layered)

```python
def main() -> None:
    cfg = configure()                               # Configuration phase
    presets = load_presets(cfg)                     # Presets phase
    overrides = build_runtime_overrides(cfg)        # Centralized runtime overrides (e.g., SOC)
    modules = initialize_modules()                  # Module lifecycle: create
    configure_modules(modules, presets, overrides)  # Module lifecycle: apply + overrides + checks
    attach_resources(modules.photovoltaic_model, cfg, presets)  # Weather + load
    execute(modules.photovoltaic_model)             # Execution phase
    outputs = extract(modules.photovoltaic_model)   # Extraction phase
    report(cfg, presets, outputs)                   # Reporting/visualization
```

This keeps `main()` < ~25 lines and self‑explanatory.

## Supporting Functions and Responsibilities (Layered)

Each top‑level phase function encapsulates the small, focused helpers. `main()` calls only these phase functions.

Configuration
- High‑level: `configure() -> SimulationConfiguration`
  - Supporting: `build_configuration_from_environment() -> SimulationConfiguration`
  - Supporting: `validate_configuration(cfg) -> None`
- High‑level: `build_runtime_overrides(cfg) -> RuntimeOverrides`
  - Purpose: Construct a single object capturing all user/scenario overrides to JSON presets (e.g., updated SOC bounds, initial SOC, dispatch mode). No side effects.

Presets
- High‑level: `load_presets(cfg) -> SamPresetFiles`
  - Supporting: `load_sam_presets_from_disk(cfg) -> SamPresetFiles`

Module lifecycle
- High‑level: `initialize_modules() -> SamModules`
  - Supporting: `create_sam_compute_modules(with_standalone_battery: bool = False) -> SamModules`
- High‑level: `configure_modules(modules, presets, overrides) -> ApplyReport`
  - Supporting: `apply_preset_values_to_modules(modules, presets) -> ApplyReport`
  - Supporting: `apply_runtime_overrides(pv, overrides) -> None`  # apply all overrides ONLY to Pvsamv1
  - Supporting: `report_apply_results(apply_report) -> None`
  - Supporting: `ensure_manual_dispatch_if_configured(pv, presets) -> None`
  - Supporting: `read_soc_bounds(pv) -> SocBounds`
  - Supporting: `report_soc_bounds(soc_bounds) -> None`
  - Supporting: `report_grid_export_settings(presets) -> None`

Resource attachers (side‑effecting)
- High‑level: `attach_resources(pv, cfg, presets) -> None`
  - Supporting: `attach_weather_resource_to_pvsam(pv, cfg) -> bool`
  - Supporting: `attach_load_profile_to_pvsam(pv, cfg) -> bool`
  - Supporting: `attach_json_load_if_present(pv, presets) -> bool`
  - Behavior: Raise `RuntimeError` if weather or load cannot be attached.

Execution
- High‑level: `execute(pv) -> None`
  - Supporting: `execute_pvsam(pv) -> bool`
  - Behavior: Raise `RuntimeError` if execution fails.

Extraction (pure)
- High‑level: `extract(pv) -> SimulationSeries`
  - Supporting: `collect_outputs(pv) -> SimulationSeries`
  - Supporting: `load_series_kw_from_model(pv) -> np.ndarray`
  - Supporting: `state_of_charge_series_percent_from_model(pv) -> np.ndarray`
  - Supporting: `solar_ac_power_series_from_flows(pv) -> np.ndarray`
  - Supporting: `per_source_load_series_kw_from_model(pv) -> tuple[np.ndarray, np.ndarray, np.ndarray]`
  - Supporting: `resolve_battery_capacity_kwh(pv) -> float`

Reporting
- High‑level: `report(cfg, presets, outputs) -> None`
  - Supporting: `print_first_day_power_allocation_table(pv, day_index=0) -> None`
  - Supporting: `print_first_day_state_of_charge_summary(pv, day_index=0) -> None`
  - Supporting: `print_human_summary(cfg, presets, outputs) -> None`
  - Supporting: `plot_quicklooks(outputs, cfg) -> None`

## Centralized Runtime Overrides

Where to overwrite JSON with specific inputs (e.g., updated SOC):

- Function name: `apply_runtime_overrides(pv, overrides) -> None`
- Lives in: Module lifecycle, called inside `configure_modules(modules, presets, overrides)` right after applying JSON presets and before reporting/validation.
- Inputs: `pv: Pvsamv1` and `overrides: RuntimeOverrides` (constructed by `build_runtime_overrides(cfg)`).
- Behavior: Idempotently set only the parameters explicitly provided in `overrides`, leaving others as‑is from JSON. Examples include:
  - `batt_minimum_SOC`, `batt_maximum_SOC`, `batt_initial_SOC`
  - Optional: `batt_dispatch_choice`, `grid_interconnection_limit_kwac`, export flags
- Rationale: Keeps all non‑JSON tweaks in a single, well‑named location for readability and auditability, ensuring a clear precedence: JSON presets → runtime overrides → execution.

### Canonical Battery Configuration

- Source of truth: Use Pvsamv1 as the canonical holder of battery parameters for detailed PV + battery runs.
- Standalone Battery module: Do not instantiate or configure `PySAM.Battery` in the default flow. If needed for separate experiments, gate it behind a flag and keep it read-only relative to Pvsamv1.
- Overrides: Apply all battery-related overrides (SOC bounds, initial SOC, dispatch mode, power limits) to Pvsamv1 only.

## Weather Timezone Preprocessing (Deferred)

- Current behavior: A fixed +8 hour shift is applied when attaching weather to approximate ET→PT alignment.
- Risk: Introducing a preprocessing shift now could double‑apply offsets.
- Decision: Defer adding any new timezone preprocessing until after the refactor is in place and visual validation (plots) can confirm alignment.
- Future plan: Replace the hard‑coded shift with a single helper `preprocess_weather_timezone(...)` (in `helpers/weather_helpers.py`) and remove the manual +8 shift to avoid double shifting.

## Data Models (use `@dataclass`)

- `SimulationConfiguration`: env/CLI inputs (county, preset paths, weather/load CSV, column names).
- `SamPresetFiles`: `{photovoltaic_preset_values, battery_preset_values}`.
- `SamModules`: `{photovoltaic_model: Pvsamv1, battery_model: Optional[Battery]}` (default `None`; avoid creating Battery by default).
- `SimulationSeries`: `{load_series_kw, state_of_charge_series_percent, solar_ac_power_series_kw, solar_to_load_series_kw, battery_to_load_series_kw, grid_to_load_series_kw}`.
- `ApplyReport`: `{pv_applied_count, pv_failed_keys, batt_applied_count, batt_failed_keys, warnings}`.
- `SocBounds`: `{min_soc, max_soc, initial_soc}`.
- `RuntimeOverrides`: Optional fields specifying parameters to overwrite JSON presets, e.g. `{min_soc, max_soc, initial_soc, dispatch_mode, grid_interconnection_limit_kwac, can_export_to_grid}`. Only fields provided are applied.

## Incremental Refactor Plan

1. Extract resource attachers and extraction helpers (pure vs side‑effecting) into their own functions.
2. Introduce `SimulationConfiguration`; replace scattered env reads with `cfg` plumbed through.
3. Extract preset I/O and application; add `ApplyReport` and `report_apply_results()`; introduce `RuntimeOverrides`, `build_runtime_overrides(cfg)`, and `apply_runtime_overrides(...)`.
4. Extract reporting helpers (`report_soc_bounds`, `report_grid_export_settings`, load/gen summaries).
5. Rewrite `main()` to the orchestrator skeleton shown above. Remove default instantiation of the standalone Battery module to avoid divergence.
6. Add unit tests for extracted helpers and guardrails.
7. Tighten `main()` to < 25 lines, keeping it narrative and readable.
8. Defer timezone preprocessing changes; keep current weather shift behavior until visual validation is in place.
9. Optional: add an `argparse` CLI mirroring env vars; print effective config at start.

## Mapping to Current Code (`pvsamv1_battery.py`)

Already present and aligned
- Dataclasses: `SimulationConfiguration`, `SamPresetFiles`, `SamModules`, `SimulationSeries`.
- Helpers: `load_json`, `apply_json`, `log_section`, `safe_head_tail`.
- Builders: `build_configuration_from_environment`, `load_sam_presets_from_disk`, `create_sam_compute_modules`.
- Attachers: `attach_weather_resource_to_pvsam`, `attach_load_profile_to_pvsam` (and `attach_load_from_csv`).
- Extraction: `solar_ac_power_series_from_flows`, `load_series_kw_from_model`, `state_of_charge_series_percent_from_model`, `per_source_load_series_kw_from_model`.
- Reporting: `print_first_day_power_allocation_table`, `print_first_day_state_of_charge_summary`, plotting helper.

Recommended additions/renames
- Add `validate_configuration`, `execute_pvsam`, `attach_json_load_if_present`.
- Add `report_apply_results`, `report_soc_bounds`, `report_grid_export_settings`.
- Add `read_soc_bounds`, `resolve_battery_capacity_kwh`.
- Collapse scattered print blocks in `main()` into the `report_*` functions.

## Notes Specific to PySAM

- Presets: apply values via `.value(k, v)`; skip non‑parameter keys like `number_inputs`. Collect failures for visibility.
- Dispatch: report `batt_dispatch_choice` from both JSON and module; avoid silent mutation unless explicitly configured.
- Outputs: prefer `.Outputs.export()` with `.get(key, [])` to tolerate version differences (e.g., `gen` vs `ac`).
- Capacity: prefer `batt_bank_installed_capacity` > `batt_computed_bank_capacity` > outputs; error if none.
- Battery module: Treat Pvsamv1 as the canonical battery configuration. Do not set values on `PySAM.Battery` in the default path to avoid divergent state.
- Weather shift: Until visual validation is added, do not introduce additional timezone preprocessing beyond existing behavior to avoid double shifting.

---

By following this structure, `main()` becomes an easy‑to‑scan narrative, while correctness improves through typed data models, explicit preconditions, small functions, and centralized error handling.
