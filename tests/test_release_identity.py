from importlib.metadata import version

from qinzora import __version__


def test_package_health_and_openapi_report_the_installed_version(api):
    client, _ = api
    installed = version("qinzora")
    assert __version__ == installed
    assert client.get("/healthz").json()["version"] == installed
    assert client.get("/openapi.json").json()["info"]["version"] == installed
