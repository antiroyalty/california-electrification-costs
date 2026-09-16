# Simon La Vieille report archive

This directory preserves *EV Integration to Ana's Project*, by Simon La Vieille,
dated August 2025. It was captured on September 15, 2026, from the
[Overleaf project](https://www.overleaf.com/project/68a362771ff44e733ac948e1).

- `report.pdf` is the downloaded 12-page Overleaf output, preserved without modification.
- `main.tex` and `reference.bib` preserve the complete text copied from Overleaf's editor.
  Character counts and text fingerprints were checked against the browser copies.
- `Figures/` contains both images recovered from the PDF at their embedded resolution.
  The filenames match the LaTeX references. These are recovered image files, not
  verified copies of the original uploaded PNG bytes.
- `SHA256SUMS` records the five archived files' checksums.

The Overleaf ZIP export was unavailable. This is a recovered report source set,
not a complete project export with revision history or unused project assets.
The preserved PDF is the authoritative record of the report's original appearance.
The archive is small enough to commit and is outside the ignored research-output directories.

Keep this snapshot unchanged. Store any later capture in a new dated directory.
Current interpretations and source gaps belong in [data_sources.yaml](../../../data_sources.yaml)
and [RESEARCH_METHODS.md](../../../RESEARCH_METHODS.md).

The source already contains errors. `AAAFuelPrices` is cited but absent from the
bibliography. `main.tex` does not explicitly load the `url` package, although its
bibliography uses `\url`. Several URLs display incorrectly in the original PDF.
The source text and original PDF retain these defects rather than silently repairing
historical evidence. This archive does not certify the report's assumptions or results.

To reuse the LaTeX, copy this directory to a working location. Load the `url`
package there and resolve the missing AAA reference before treating it as a clean build.
Both referenced figures are present. The catalogue preserves usable source URLs
separately from the original bibliography.
