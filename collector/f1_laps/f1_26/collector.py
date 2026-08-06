import re
from collections import defaultdict
from typing import Any, DefaultDict, Dict, Iterator, List
from urllib.parse import unquote, urljoin, urlparse
from typing import ClassVar
from collector.enums import GameId


import requests
from bs4 import BeautifulSoup

from collector.f1_laps.mapper import F1SetupLapsMapper
from collector.f1_laps.f1_laps_collector import F1LapsCollector
from collector.f1_laps.utils.constants import (DETAIL_LABELS, SETTING_LABELS)


TRACK_PATH = re.compile(r"/f1-\d+/setups/([^/]+)/?$")
SETUP_PATH = re.compile(
    r"/f1-\d+/setups/([^/]+)/([0-9a-f]{8}-[0-9a-f-]{27,})/?$", re.IGNORECASE
)

class F1LapsF126Collector(F1LapsCollector):
    """Collect every F1Laps setup, ordered by track and dry/wet condition."""
    GameId = GameId.F1_26
    game_url: ClassVar[str] = (F1LapsCollector.base_url + "f1-26/setups/"
    )
    def __init__(self) -> None:
        super().__init__()        
        self.mapper = F1SetupLapsMapper()
        self._tracks: Dict[str, Dict[str, str]] = {}

    @staticmethod
    def _strings(html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        return [text.strip() for text in soup.stripped_strings if text.strip()]

    @staticmethod
    def _pairs(strings: List[str], labels: Dict[str, str]) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for index, text in enumerate(strings[:-1]):
            if text in labels:
                result[labels[text]] = strings[index + 1].replace("\xa0", " ").strip()
        return result

    def _parse_tracks(self, html: str, base_url: str) -> Iterator[Dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        for anchor in soup.find_all("a", href=True):
            url = urljoin(base_url, anchor["href"])
            match = TRACK_PATH.search(urlparse(url).path)
            if not match or url in seen:
                continue
            slug = unquote(match.group(1)).strip().lower()
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                continue
            seen.add(url)
            text = list(anchor.stripped_strings)
            yield {
                "slug": slug,
                "country": text[0] if text else slug.replace("-", " ").title(),
                "circuit": text[1] if len(text) > 1 else text[0] if text else slug,
                "url": url,
            }

    def _parse_listing(self, html: str, base_url: str) -> Iterator[str]:
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        for anchor in soup.find_all("a", href=True):
            url = urljoin(base_url, anchor["href"])
            if SETUP_PATH.search(urlparse(url).path) and url not in seen:
                seen.add(url)
                yield url

    def _parse_setup(self, html: str, url: str, track: Dict[str, str], weather: str) -> Dict[str, Any]:
        strings = self._strings(html)
        details = self._pairs(strings, DETAIL_LABELS)
        settings = self._pairs(strings, SETTING_LABELS)
        match = SETUP_PATH.search(urlparse(url).path)
        heading = next((text for text in strings if " Setup (" in text), "")
        game_match = re.search(r"F1\s+(\d+)", heading)
        try:
            by_index = strings.index(next(text for text in strings if text.startswith("by ")))
            user = strings[by_index][3:].strip()
        except (StopIteration, ValueError):
            user = None

        return {
            "id": match.group(2) if match else url,
            "url": url,
            "game": f"F1 {game_match.group(1)}" if game_match else None,
            "country": track["country"],
            "circuit": track["circuit"],
            "car": details.get("team"),
            "weather": weather,
            "setup": {"user": user, **details, "settings": settings},
        }

    # Kept for callers of the original parser and for simple fixture-based tests.
    def _parse(self, html: str) -> Iterator[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup.select("[data-setup-id]"):
            yield {
                "id": element.get("data-setup-id"),
                "url": element.get("href"),
                "circuit": element.get("data-circuit"),
                "car": element.get("data-car"),
            }

    def get_tracks(self) -> List[str]:       
        if not self.game_url:
            raise ValueError("Set url before running this collector")

        response = self.request_api(self.game_url, method="GET", json_response=False)
        if response is None:
            return []

        self._tracks = {
            track["slug"]: track
            for track in self._parse_tracks(response.text, self.game_url)
        }
        return list(self._tracks)

    def get_setups(self, track_name: str, weather: str
    ) -> Iterator[Dict[str, Any]]:
        """Yield every setup for one track and one weather condition."""
        if weather not in ("dry", "wet"):
            raise ValueError("weather must be 'dry' or 'wet'")

        track = self._tracks.get(track_name)
        if track is None:
            raise ValueError(
                f"Unknown track '{track_name}'. Call get_tracks() first."
            )

        listing_url = track["url"]
        if weather == "wet":
            listing_url = urljoin(listing_url.rstrip("/") + "/", "wet/")

        listing = self.request_api(listing_url, method="GET", json_response=False)
        if listing is None:
            return

        for setup_url in self._parse_listing(listing.text, listing_url):
            detail = self.request_api(setup_url, method="GET", json_response=False)
            if detail is None:
                continue
            raw = self._parse_setup(detail.text, setup_url, track, weather)
            yield self.mapper.map(raw).to_dict()

    def get_setups_by_track(self, track_name: str) -> List[Dict[str, Any]]:
        """Return all dry and wet setups from one track."""
        if not re.fullmatch(r"[a-z0-9-]+", track_name):
            raise ValueError("track_name must be a valid F1Laps track slug")

        if track_name not in self._tracks:
            track_url = urljoin(self.game_url.rstrip("/") + "/", f"{track_name}/",)
            display_name = track_name.replace("-", " ").title()
            self._tracks[track_name] = {
                "slug": track_name,
                "country": display_name,
                "circuit": display_name,
                "url": track_url,
            }

        setups: List[Dict[str, Any]] = []
        for weather in ("dry", "wet"):
            setups.extend(self.get_setups(track_name, weather))
        return setups

    def run(self) -> Iterator[Dict[str, Any]]:
        for track_name in self.get_tracks():
            yield from self.get_setups_by_track(track_name)

    def collect_organized(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """Return ``{country: {dry: [...], wet: [...]}}`` for JSON export/storage."""
        grouped: DefaultDict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
            lambda: {"dry": [], "wet": []}
        )
        for item in self.run():
            country = item["setup"].pop("country", item["circuit"])
            grouped[country][item["weather"]].append(item)
        return dict(grouped)

    # Implement BaseCollector abstract method(s) with a useful default.
    def request_api(self, url: str, method: str = "GET", json_response: bool = True, **kwargs):
        """Simple HTTP requester used by this collector.

        Returns a requests.Response when successful, or None on error.
        If json_response is True, attempts to return response.json(); otherwise
        returns the full response object so callers can access .text.
        """
        try:
            resp = requests.request(method, url, timeout=15, **kwargs)
            resp.raise_for_status()
            if json_response:
                try:
                    return resp.json()
                except ValueError:
                    return None
            return resp
        except requests.RequestException:
            return None
