import pytest

from collector.registry import SCRAPERS
from collector.ea_setup.ea_setup_scrapper import EASetupCollector
from conftest import FakeResponse


def test_ea_setup_collector_is_registered() -> None:
    assert SCRAPERS["ea_setup"] is EASetupCollector


def test_ea_setup_collector_parses_setup(setup_html: str) -> None:
    items = list(EASetupCollector()._parse(setup_html))

    assert items == [
        {
            "id": "42",
            "url": "https://example.test/setups/42",
            "circuit": "Monza",
            "car": "Ferrari",
        }
    ]


def test_ea_setup_collector_fetches_and_normalizes_setup(
    monkeypatch: pytest.MonkeyPatch, setup_html: str
) -> None:
    target_url = "https://ea-setup.example.test/setups"
    monkeypatch.setattr("collector.ea_setup.ea_setup_scrapper.EA_SETUP_URL", target_url)
    scraper = EASetupCollector()
    calls = []

    def fake_request(url: str, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(setup_html)

    monkeypatch.setattr(scraper, "request_api", fake_request)

    assert list(scraper.run()) == [
        {
            "source": "ea_setup",
            "source_id": "42",
            "game": None,
            "circuit": "Monza",
            "car": "Ferrari",
            "platform": None,
            "weather": None,
            "setup": None,
            "source_url": "https://example.test/setups/42",
        }
    ]
    assert calls == [(target_url, {"method": "GET", "json_response": False})]


def test_ea_setup_collector_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("collector.ea_setup.ea_setup_scrapper.EA_SETUP_URL", "")

    with pytest.raises(ValueError, match="EA_SETUP_URL"):
        list(EASetupCollector().run())
