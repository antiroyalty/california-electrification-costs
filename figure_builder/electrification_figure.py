"""Render one matched-adoption figure from a verified four-case source."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from figure_builder import git_short_sha
from figure_builder import charts
from figure_builder.electrification import load_electrification_costs
from figure_builder.metadata import file_identity


def render_adoption_figure(source: str | Path, output_prefix: str | Path) -> dict:
    """Save PNG/PDF and a receipt with the exact plotted source and statistics."""
    source, prefix = Path(source), Path(output_prefix)
    outputs = [Path(f"{prefix}{suffix}") for suffix in (".png", ".pdf", ".json")]
    inputs = [source, source.with_suffix(".manifest.json")]
    if {p.resolve() for p in outputs} & {p.resolve() for p in inputs}:
        raise ValueError("Figure outputs cannot replace the comparison source or receipt")
    source_identity = file_identity(source)
    costs = load_electrification_costs(source)
    fig, stats = charts.plot_matched_adoption_savings(costs)
    import matplotlib.pyplot as plt

    try:
        if file_identity(source) != source_identity:
            raise ValueError("Comparison source changed during figure generation")
        prefix.parent.mkdir(parents=True, exist_ok=True)
        for path in outputs[:2]:
            fig.savefig(path, facecolor="white", dpi=180)
    finally:
        plt.close(fig)
    receipt = {
        "source": source_identity, "source_manifest": file_identity(inputs[1]),
        "reporting_git_sha": git_short_sha(), "chart_code": file_identity(charts.__file__),
        "renderer_code": file_identity(__file__), "statistics": stats,
        "artifacts": [file_identity(path) for path in outputs[:2]],
    }
    outputs[2].write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    render_adoption_figure(args.source, args.output_prefix)
    print(f"Wrote PNG, PDF, and figure receipt: {args.output_prefix}")


if __name__ == "__main__":
    main()
