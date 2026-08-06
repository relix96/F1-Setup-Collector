import re
from typing import Any, Dict, Iterator, List

from bs4 import BeautifulSoup

from collector.ea_setup.ea_setup_mapper import EASetupMapper
from collector.base_collector import BaseCollector
from collector.enums import GameId, SourceId
from collector.settings import EA_SETUP_URL


class EASetupCollector(BaseCollector):
    """Starting point for the EA setups website collector."""

    GameId = GameId.F1_26
    SourceId = SourceId.EA_SETUP

    def __init__(self) -> None:
        super().__init__()
        self.mapper = EASetupMapper()

    def _parse(self, html: str) -> Iterator[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        # Adapt the selector and fields after confirming the target page structure.
        for element in soup.select("[data-setup-id]"):
            yield {
                "id": element.get("data-setup-id"),
                "url": element.get("href"),
                "circuit": element.get("data-circuit"),
                "car": element.get("data-car"),
            }

    def run(self) -> Iterator[Dict[str, Any]]:
        if not EA_SETUP_URL:
            raise ValueError("Set EA_SETUP_URL before running this collector")
        response = self.request_api(EA_SETUP_URL, method="GET", json_response=False)
        if response is None:
            return
        for raw_item in self._parse(response.text):
            yield self.mapper.map(raw_item).to_dict()

    def get_tracks(self) -> List[str]:
        """Return unique circuit slugs exposed by the EA setups page."""
        tracks: List[str] = []
        seen = set()
        for item in self.run():
            circuit = item.get("circuit")
            if not circuit:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", circuit.lower()).strip("-")
            if slug and slug not in seen:
                seen.add(slug)
                tracks.append(slug)
        return tracks

    def get_setups_by_track(self, track_name: str) -> List[Dict[str, Any]]:
        """Return EA setups whose circuit matches the supplied track slug."""
        if not re.fullmatch(r"[a-z0-9-]+", track_name):
            raise ValueError("track_name must be a valid track slug")

        setups: List[Dict[str, Any]] = []
        for item in self.run():
            circuit = item.get("circuit") or ""
            slug = re.sub(r"[^a-z0-9]+", "-", circuit.lower()).strip("-")
            if slug == track_name:
                setups.append(item)
        return setups


# Backwards compatibility for the previous public class name.
EASetupScrapper = EASetupCollector
