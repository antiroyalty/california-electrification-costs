"""pytest configuration: injects test docstrings into the pytest-html report.

Adds a "Description" column to the HTML results table populated from each
test function's docstring. Run with:

    python -m pytest tests/ -v --html=test_report.html --self-contained-html
"""
import pytest


def pytest_html_results_table_header(cells):
    cells.insert(2, "<th>Description</th>")


def pytest_html_results_table_row(report, cells):
    description = getattr(report, "description", "")
    cells.insert(2, f"<td>{description}</td>")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.description = str(item.function.__doc__ or "")
