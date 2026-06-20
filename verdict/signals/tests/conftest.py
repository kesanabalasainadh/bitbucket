import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", default=False, help="run live API tests"
    )

def pytest_configure(config):
    config.addinivalue_line("markers", "live: mark test as requiring live API credentials")

def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="need --live option to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
