import pytest
from app import create_app, db
from config import TestConfig


def pytest_addoption(parser):
    parser.addoption(
        "--run-mysql-integration",
        action="store_true",
        default=False,
        help="run integration tests against the dedicated MySQL test database",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-mysql-integration"):
        return
    skip_mysql = pytest.mark.skip(reason="pass --run-mysql-integration to run mutating MySQL integration tests")
    for item in items:
        if item.path.name == "test_mysql_integration.py":
            item.add_marker(skip_mysql)


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()

