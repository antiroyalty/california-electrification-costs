# Repository Guidelines

## Project Structure & Module Organization
- Root: pipeline steps `step<N>_<task>.py`, orchestrator `cost_service.py`, configs `scenarios.py`, helpers in `main_helpers.py`.
- `helpers/`: domain utilities (rates, maps, capital costs, etc.). Import with `from helpers import ...`.
- `data/`: inputs; `data/loadprofiles/`: generated outputs and intermediate artifacts.
- `tests/`: pytest suites, mirroring modules (files named like `helpers-test.py`, `step4_build_gas_load_profiles-test.py`).
- `notebooks/`, `visualizations/`, `analysis_results/`, `SAM_configuration/`, `appliances/`: exploratory work, assets, and configuration.

## Build, Test, and Development Commands
- Create venv: `python3 -m venv .venv && source .venv/bin/activate`.
- Install deps (see README list):
  `pip install PySAM pandas geopandas folium numpy requests boto3 botocore geopy python-dotenv pytest matplotlib`.
- Run a scenario: `python3 cost_service.py baseline` (see `SCENARIOS` in `scenarios.py`).
- Run tests: `pytest -q` or a single test `pytest tests/step4_build_gas_load_profiles-test.py::test_process_non_baseline_scenario -q`.

## Coding Style & Naming Conventions
- Python 3; follow PEP 8, 4‑space indentation, 88–100 char lines.
- Names: snake_case for modules/functions, PascalCase for classes, UPPER_SNAKE_CASE for constants.
- Pipeline files: `step<N>_<short_description>.py` (e.g., `step10_get_loads_for_rates.py`).
- Prefer explicit imports; keep module boundaries clear (use `helpers/` for shared logic).
- Optional formatting: `black .` and linting: `ruff .` if installed (not enforced in CI).

## Research Code Principles (No Silent Fallbacks)
- Do not implement silent fallbacks or heuristics that “pick something reasonable” when expected data is missing or malformed.
- When an expected file, row, column, or plan selection is not found, raise a clear exception rather than returning a surrogate value.
- Avoid using “first numeric value” or similar patterns as defaults — these mask upstream issues and can corrupt results.
- Only the main, explicitly specified path of execution should run; anything else should fail loudly so it can be fixed.

## Testing Guidelines
- Framework: pytest. Co‑locate tests in `tests/` mirroring file names with `-test.py` suffix.
- Write focused unit tests for new/changed functions; include edge cases and error paths.
- Fast tests by default; mark slow/integration if applicable using `@pytest.mark.slow`.
- Run locally: `pytest -q`. Add fixtures/mocks to avoid network/large I/O.

## Commit & Pull Request Guidelines
- Commits: imperative mood, concise subject, scope in message (e.g., "step4: fix county aggregation").
- PRs: clear description, linked issues, affected scenarios/counties, repro steps, and sample outputs (paths under `data/loadprofiles/`) or screenshots for visuals.
- Ensure tests pass and `cost_service.py <scenario>` runs for at least one representative county group.

## Security & Configuration
- Secrets: use `.env` (ignored). Required: `NREL_WEATHER_API_KEY`. Never commit credentials or large datasets.
- Large files and generated outputs should remain under ignored paths (see `.gitignore`).

## Research methods documentation

The maintained narrative is [Research methods and approach](docs/RESEARCH_METHODS.md).
The technical formula manifest is [docs/methods.yaml](docs/methods.yaml), which
also supplies the generated diagnostics.

Whenever code files are modified, check both `docs/methods.yaml` and
`docs/RESEARCH_METHODS.md` before completing the commit-sized change. This
includes changes to pipeline code, helpers, scripts, tests, and figure generation.

- Update each affected file in the same review unit when a change affects research
  questions, inputs, assumptions, equations, constraints, optimization, comparisons,
  validation, or interpretation. Keep the technical formulas and readable
  narrative consistent with each other and with the implemented code.
- Keep the dedicated **Known limitations, constraints, and potential future
  improvements** section current. Explain the boundary, its likely effect or
  uncertainty, and a possible improvement. Future ideas are not automatically
  prerequisites for publication.
- Write for an informed lay reader through an academic reader. Explain the
  research meaning first, define necessary terms, and link to technical details.
  Keep the narrative in Markdown with LaTeX equations and defined symbols.
  Maintain one narrative source; treat any LaTeX export as derived until the
  project explicitly moves its maintained methods to the paper's LaTeX source.
- Distinguish implemented behavior, approved pending changes, and future ideas.
  Do not describe an approved method as implemented or new results as verified
  before the corresponding code and validation exist.
- A file needs no edit if its content remains accurate. The review summary must
  confirm that both files were checked and identify updates or briefly explain
  why none were needed. Do not add filler or duplicate a development log.

## Change-management and review protocol

All implementation work must proceed as a sequence of small, reviewable commits.

Before editing files, Codex must propose a commit plan. For each proposed commit, list:

- its single conceptual purpose;
- the files expected to change;
- the tests or validations that will establish correctness;
- any dependency on an earlier proposed commit.

Codex must work on only one proposed commit at a time. Each commit should:

- represent one coherent behavioral, architectural, data, testing, or documentation change;
- include the tests necessary to validate its behavior;
- leave the repository in a usable state with the relevant test suite passing;
- avoid unrelated fixes, formatting changes, or opportunistic refactors;
- remain reasonably small and understandable in isolation.

After completing one commit-sized change, Codex must stop and provide:

- a concise description of the resulting behavior;
- `git diff --stat`;
- the important files and decisions to review;
- tests run and their results;
- known limitations or deferred work.

Codex must not begin editing files for the next commit until:

1. the current change has been reviewed;
2. requested corrections have been resolved;
3. the change has been committed by the user or Codex;
4. the resulting commit SHA has been identified; and
5. the working tree is clean.

Codex must not create a commit unless the user has explicitly authorized it. The user may instead commit the reviewed change themselves.

When a feature requires multiple commits, Codex may present the complete proposed commit series in advance, but the review and commit gate still applies between every commit.

Discovered issues outside the active commit’s scope must be reported and recorded as follow-up work. They must not be silently included in the active change.

Any generated patch must be based on the target repository’s current HEAD and verified with `git apply --check` against that exact checkout before delivery.

## Writing style

Use clear technical English inspired by ASD-STE100 Simplified Technical English.

Apply these rules to explanations, plans, documentation, comments, and other prose:

- Put the main point first.
- Use short, direct sentences.
- Prefer subject–verb–object sentence structure.
- Use active voice when the actor is known.
- Express one main idea per sentence and one topic per paragraph.
- Use common, concrete words.
- Use one consistent term for each concept.
- Avoid jargon, idioms, metaphors, buzzwords, and unnecessary abbreviations.
- Define a necessary technical term the first time you use it.
- Avoid inverted syntax, nested clauses, long introductions, and abstract noun phrases.
- Use lists when they make steps, options, or conditions easier to understand.
- Keep sentences under 25 words when practical.
- Write complete, natural sentences. Do not omit necessary subjects, verbs, or articles.
- Preserve technical accuracy. Keep exact code identifiers, API names, error messages, and required domain terms. Explain them in plain language when necessary.

Before sending prose, rewrite any sentence that a reader might need to parse twice.

```markdown
## Engineering design principles

Use a domain-first, explicit, and testable style. Assumptions, units, dependencies, and failure modes should be clear from the code.

### Model the domain first

- Define domain concepts and invariants before building UI, API, or persistence code.
- Keep calculations independent of frameworks and presentation libraries.
- Give each module one clear responsibility.
- Introduce abstractions only when they represent a real domain boundary.

### Make values explicit

- Include units and time bases in names, such as `energyUsageKwh`, `annualCostUsd`, and `durationMinutes`.
- Distinguish concepts such as power and energy, gross and net cost, and local time and UTC.
- Keep assumptions and important constants close to the calculations using them.
- Do not use unexplained numbers or ambiguous quantities.

### Prefer composition and pure calculations

- Compose behavior from small functions and interfaces.
- Pass dependencies through parameters or named options rather than importing global services.
- Prefer pure functions for calculations and conversions.
- Use mutable state only when the modeled process genuinely changes over time.
- Derive values that can be recomputed instead of storing duplicates.

Use this flow:

1. Acquire external data.
2. Validate its structure and invariants.
3. Normalize it into trusted domain values.
4. Apply domain calculations.
5. Produce an explainable result.
6. Present or serialize it.

### Represent states and errors precisely

- Distinguish zero, missing, loading, unavailable, invalid, and not applicable.
- Use discriminated unions and exhaustive branching for meaningful states.
- Validate external data while it is still `unknown`.
- Avoid unsafe type assertions. An assertion is not validation.
- Fail clearly when an internal invariant is violated.
- Do not invent fallback values that produce plausible but unsupported results.
- Convert expected external failures into typed outcomes callers can handle.

### Make results explainable

- Prefer itemized results over unexplained totals.
- Preserve the inputs, assumptions, provenance, and components needed to explain an output.
- Keep calculation separate from formatting and presentation.
- Comments should explain why, sources, unit derivations, constraints, or uncertainty.
- Do not comment obvious syntax.
- Use specific TODOs that identify the unresolved question and relevant source.

Prefer:

`TODO(name): Verify whether this rate includes fixed charges; source: <reference>`

Avoid:

`TODO: Fix this`

### Test behavior and boundaries

- Test domain behavior rather than implementation details.
- Use realistic, deterministic fixtures.
- Cover normal cases, boundaries, values around boundaries, and failures.
- Verify that itemized components reconcile to displayed totals.
- Use approximate equality only for genuinely approximate calculations.
- Inject external dependencies instead of using live services in unit tests.
- Add regression tests for bug fixes when practical.

### Keep application code focused

- Structure orchestration as a readable sequence of domain steps.
- Keep UI components focused on presentation, interaction, or composition.
- Do not place core calculations or policies inside components.
- Represent loading, unavailable, invalid, empty, and ready states deliberately.
- Prefer straightforward code over clever or compressed expressions.
- Follow the architectural principles without copying outdated implementation details.

## Review checklist

Before considering a change complete, ask:

- Is the domain independent of the interface?
- Are quantities named with units and time basis?
- Are dependencies explicit and replaceable?
- Could the calculation be pure?
- Are missing and invalid states distinct?
- Is external data validated before use?
- Can the result be explained from its inputs?
- Are assumptions and uncertainty documented?
- Do tests cover boundaries and failures?
- Is the implementation straightforward to verify?
```
