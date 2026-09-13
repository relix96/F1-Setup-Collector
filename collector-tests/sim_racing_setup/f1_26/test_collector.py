from dataclasses import dataclass

import pytest

from collector.collectorFactory import CollectorFactory
from collector.enums import GameId, SourceId
from collector.sim_racing_setup.f1_26.collector import (
    SimRacingSetupF126Collector,
)


@dataclass
class FakeResponse:
    text: str


def collector() -> SimRacingSetupF126Collector:
    result = CollectorFactory.create_collector(
        GameId.F1_26,
        SourceId.SIM_RACING_SETUP,
    )
    assert isinstance(result, SimRacingSetupF126Collector)
    return result


def settings_html() -> str:
    values = {
        "Front Wing Aero": "50",
        "Rear Wing Aero": "9",
        "Differential Adjustment On Throttle": "100",
        "Differential Adjustment Off Throttle": "80",
        "Front Camber": "-3.5",
        "Rear Camber": "-2",
        "Front Toe": "0",
        "Rear Toe": "0.1",
        "Front Suspension": "40",
        "Rear Suspension": "20",
        "Front Anti-Roll Bar": "1",
        "Rear Anti-Roll Bar": "10",
        "Front Ride Height": "22",
        "Rear Ride Height": "42",
        "Brake Pressure": "100",
        "Brake Bias": "56",
        "Front Right Tyre Pressure": "28.5",
        "Front Left Tyre Pressure": "28.5",
        "Rear Right Tyre Pressure": "21",
        "Rear Left Tyre Pressure": "21",
    }
    return "".join(
        '<div class="setup-section"><div class="setup-part-100">'
        f'<div class="setup-part-name">{name}:</div>'
        f'<div class="setup-part-number">{value}</div></div></div>'
        for name, value in values.items()
    )


def test_discovers_all_circuit_urls_once() -> None:
    subject = collector()
    html = """
      <a href="/setups/f1-26/australian-gp-setups/">Australia</a>
      <a href="https://simracingsetup.com/setups/f1-26/australian-gp-setups/">Duplicate</a>
      <a href="/setups/f1-26/italian-gp-setups/">Monza</a>
      <a href="/setups/f1-25/australian-gp-setups/">Old game</a>
    """

    tracks = list(subject._parse_tracks(html))

    assert tracks == [
        {
            "slug": "australian-gp-setups",
            "circuit": "Melbourne Grand Prix Circuit",
            "url": "https://simracingsetup.com/setups/f1-26/australian-gp-setups/",
        },
        {
            "slug": "italian-gp-setups",
            "circuit": "Autodromo Nazionale Monza",
            "url": "https://simracingsetup.com/setups/f1-26/italian-gp-setups/",
        },
    ]


def test_listing_finds_community_and_pro_pages() -> None:
    subject = collector()
    html = """
      <div class="car-setup-archive-box-100">
        <a href="/setups/f1-26-setups/australia-ferrari-dry-123/">
          <span class="team-name-color Ferrari">Ferrari</span>
        </a>
      </div>
      <div class="car-setup-archive-box-100 pro-setup">
        <a href="/setups/f1-26-setups-pro/australia/">
          <span class="team-name-color Williams">Williams</span>
        </a>
      </div>
    """

    items = list(subject._parse_listing(html, subject.game_url))

    assert [item["kind"] for item in items] == ["community", "pro"]
    assert [item["car"] for item in items] == ["Ferrari", "Williams"]


def test_parses_community_setup_into_shared_contract() -> None:
    subject = collector()
    track = {
        "slug": "australian-gp-setups",
        "circuit": "Melbourne Grand Prix Circuit",
        "url": subject.game_url + "australian-gp-setups/",
    }
    html = f"""
      <span class="author-name fn">Created by Driver</span>
      <time class="entry-date published">August 29, 2026</time>
      <div class="car-setup-single-post-box">
        <div class="listing-detail-part"><p>Team</p><strong>McLaren</strong></div>
        <div class="listing-detail-part"><p>Lap Time</p>1:16.999</div>
        <div class="listing-detail-part"><p>Session Type</p>Short Qualifying Setup</div>
        <div class="listing-detail-part"><p>Conditions</p><span>Dry</span>Wheel</div>
      </div>
      {settings_html()}
    """

    result = subject._parse_community_setup(
        html,
        "https://simracingsetup.com/setups/f1-26-setups/example/",
        "example",
        track,
    )

    assert result is not None
    assert result["source"] == "sim_racing_setup"
    assert result["source_id"] == "example"
    assert result["circuit"] == "Melbourne Grand Prix Circuit"
    assert result["car"] == "McLaren"
    assert result["weather"] == "dry"
    assert result["setup"]["user"] == "Driver"
    assert result["setup"]["session"] == "Short Qualifying"
    assert result["setup"]["lap_time"] == "1:16.999"
    assert result["setup"]["settings"]["brakes"] == {
        "brake_pressure": "100",
        "front_brake_bias": "56",
    }


def test_parses_only_complete_public_pro_setups() -> None:
    subject = collector()
    track = {
        "slug": "australian-gp-setups",
        "circuit": "Melbourne Grand Prix Circuit",
        "url": subject.game_url + "australian-gp-setups/",
    }
    groups = {
        "Aerodynamics": [50, 10],
        "Transmission": [100, 80],
        "Geometry": [-3.5, -2, 0, 0.1],
        "Suspension": [40, 41, 1, 18, 23, 42],
        "Brakes": [56, 100],
        "Tyres": [29, 29, 20.5, 20.5],
    }
    group_html = "".join(
        '<div class="setup-part-group">'
        f'<span class="setup-part-title">{name}</span><ul class="setup-numbers">'
        + "".join(f'<li class="setup-part-number">{value}</li>' for value in values)
        + "</ul></div>"
        for name, values in groups.items()
    )
    html = f"""
      <p>Created by pro F1 sim racer Istvan Puki.</p>
      <div class="car-setup-pro-box">
        <h3 class="setup-title">Esports Quali Setup</h3>
        {group_html}
        <div class="setup-part-group description">
          <span class="setup-part-description">Reference Lap Time: 1:16.239</span>
        </div>
        <div class="setup-part-group description">
          <span class="setup-part-description">Updated: 27 August 2026</span>
        </div>
      </div>
      <div class="car-setup-pro-box">
        <h3 class="setup-title">Locked Setup</h3>
      </div>
    """

    results = list(
        subject._parse_pro_setups(
            html,
            "https://simracingsetup.com/setups/f1-26-setups-pro/australia/",
            track,
            "Williams",
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result["source_id"] == "pro:australia:esports-quali-setup"
    assert result["setup"]["user"] == "Istvan Puki"
    assert result["setup"]["session"] == "Qualifying"
    assert result["setup"]["lap_time"] == "1:16.239"
    assert result["setup"]["date"] == "27 August 2026"
    assert result["setup"]["settings"]["brakes"] == {
        "brake_pressure": "100",
        "front_brake_bias": "56",
    }


def test_collects_each_listing_detail_once(monkeypatch: pytest.MonkeyPatch) -> None:
    subject = collector()
    subject._tracks = {
        "australian-gp-setups": {
            "slug": "australian-gp-setups",
            "circuit": "Melbourne Grand Prix Circuit",
            "url": subject.game_url + "australian-gp-setups/",
        }
    }
    listing = """
      <div class="car-setup-archive-box-100">
        <a href="/setups/f1-26-setups/example/">Example</a>
      </div>
    """
    calls: list[str] = []

    def request(url: str, **kwargs):
        calls.append(url)
        return FakeResponse(listing if url == subject._tracks["australian-gp-setups"]["url"] else settings_html())

    monkeypatch.setattr(subject, "request_api", request)
    monkeypatch.setattr(
        subject,
        "_parse_community_setup",
        lambda *args: {"source_id": "example"},
    )

    assert subject.get_setups_by_track("australian-gp-setups") == [
        {"source_id": "example"}
    ]
    assert len(calls) == 2


@pytest.mark.live
def test_live_australia_has_community_and_public_pro_setups() -> None:
    results = collector().get_setups_by_track("australian-gp-setups")

    assert any(item["source_id"].startswith("pro:australia:") for item in results)
    assert any(not item["source_id"].startswith("pro:") for item in results)
