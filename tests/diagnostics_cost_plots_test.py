import base64

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from helpers.diagnostics_cost_plots import _fig_to_b64  # noqa: E402


@pytest.fixture(autouse=True)
def close_test_figures():
    plt.close("all")
    yield
    plt.close("all")


def test_fig_to_b64_closes_serialized_figure() -> None:
    fig, ax = plt.subplots()
    figure_number = fig.number
    ax.plot([0, 1], [0, 1])

    encoded = _fig_to_b64(fig)

    assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")
    assert figure_number not in plt.get_fignums()


def test_fig_to_b64_closes_figure_when_serialization_fails(monkeypatch) -> None:
    fig, _ = plt.subplots()
    figure_number = fig.number

    def fail_to_save(*args, **kwargs):
        raise RuntimeError("synthetic save failure")

    monkeypatch.setattr(fig, "savefig", fail_to_save)

    with pytest.raises(RuntimeError, match="synthetic save failure"):
        _fig_to_b64(fig)

    assert figure_number not in plt.get_fignums()
