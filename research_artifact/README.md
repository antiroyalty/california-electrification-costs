# Research companion exports

This package creates versioned data releases for the public web companion to
the research paper. It packages existing Step 10 hourly outputs. It does not
run an optimization, alter a scenario, choose a new system size, or calculate
a new tariff result.

Every release records:

- The scenarios exactly as defined in `scenarios.py`
- The selected modeled counties and housing type
- The repository commit and whether the working tree was dirty
- The exact SHA-256 hash of every source CSV and exported profile
- The complete 8,760-hour series and annual totals

Scenarios and counties must be selected explicitly. Missing files, missing
columns, invalid values, non-hourly timestamps, and incomplete years fail the
export rather than producing a partial artifact.

Example draft export:

```bash
python -m research_artifact.export \
  --release-id paper-draft-2026-08 \
  --scenario baseline_coopt \
  --scenario heat_pump_coopt \
  --counties alameda los-angeles san-diego
```

The command writes `web_artifacts/<release-id>/manifest.json` and one profile
per scenario and county. Release directories are immutable: the exporter will
not replace an existing release ID. Use a new release ID when the paper model
or inputs change.

For a publication release, run the exporter from the clean commit used for the
paper and verify that `researchRepository.dirtyAtExport` is `false`.

## Completed-run validation

Run the fail-loud validator after the complete pipeline finishes:

```bash
python3 -m research_artifact.validation baseline_coopt --all-counties
```

The validator requires all 47 county outputs and shared capital-cost files. It
checks hourly completeness, meter direction, energy balance, tariff identity,
hourly prices, bill ranges, cost reconciliation, capacity bounds, and source
hashes. It writes immutable JSON and text reports under
`analysis_results/research_validation/`.

The default command requires a clean repository. It also requires generated
artifacts to be newer than the source commit. The explicit `--allow-dirty` and
`--allow-stale-artifacts` options support diagnosis only. Do not use those
options for a publication validation report.
