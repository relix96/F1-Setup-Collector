import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import Any, ClassVar, Dict, Iterator, List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from collector.enums import GameId
from collector.settings import COLLECTOR_CONCURRENCY
from collector.sim_racing_setup.sim_racing_setup_collector import (
    SimRacingSetupCollector,
)
from collector.utils.logger import get_logger


logger = get_logger(__name__)
TRACK_PATH = re.compile(r"^/setups/f1-26/([a-z0-9-]+-gp-setups)/?$", re.I)
COMMUNITY_SETUP_PATH = re.compile(
    r"^/setups/f1-26-setups/([a-z0-9-]+)/?$", re.I
)
PRO_SETUP_PATH = re.compile(
    r"^/setups/f1-26-setups-pro/(?:tracks/)?([a-z0-9-]+)/?$", re.I
)

SETTING_LABELS = {
    "front wing aero": "front_wing",
    "rear wing aero": "rear_wing",
    "differential adjustment on throttle": "differential_on_throttle",
    "differential adjustment off throttle": "differential_off_throttle",
    "front camber": "front_camber",
    "rear camber": "rear_camber",
    "front toe": "front_toe",
    "rear toe": "rear_toe",
    "front suspension": "front_suspension",
    "rear suspension": "rear_suspension",
    "front anti-roll bar": "front_anti_roll_bar",
    "rear anti-roll bar": "rear_anti_roll_bar",
    "front ride height": "front_ride_height",
    "rear ride height": "rear_ride_height",
    "brake pressure": "brake_pressure",
    "brake bias": "front_brake_bias",
    "front right tyre pressure": "front_right_tyre_pressure",
    "front left tyre pressure": "front_left_tyre_pressure",
    "rear right tyre pressure": "rear_right_tyre_pressure",
    "rear left tyre pressure": "rear_left_tyre_pressure",
}

PRO_GROUP_FIELDS = {
    "aerodynamics": ("front_wing", "rear_wing"),
    "transmission": (
        "differential_on_throttle",
        "differential_off_throttle",
    ),
    "geometry": ("front_camber", "rear_camber", "front_toe", "rear_toe"),
    "suspension": (
        "front_suspension",
        "rear_suspension",
        "front_anti_roll_bar",
        "rear_anti_roll_bar",
        "front_ride_height",
        "rear_ride_height",
    ),
    # The Pro page displays brake bias first and pressure second.
    "brakes": ("front_brake_bias", "brake_pressure"),
    "tyres": (
        "front_left_tyre_pressure",
        "front_right_tyre_pressure",
        "rear_left_tyre_pressure",
        "rear_right_tyre_pressure",
    ),
}

TRACK_NAMES = {
    "australian-gp-setups": "Melbourne Grand Prix Circuit",
    "china-gp-setups": "Shanghai International Circuit",
    "japanese-gp-setups": "Suzuka International Racing Course",
    "bahrain-gp-setups": "Bahrain International Circuit",
    "saudi-arabian-gp-setups": "Jeddah Street Circuit",
    "miami-gp-setups": "Miami International Autodrome",
    "canadian-gp-setups": "Circuit Gilles-Villeneuve",
    "monaco-gp-setups": "Circuit de Monaco",
    "spanish-gp-setups": "Circuit de Barcelona-Catalunya",
    "austrian-gp-setups": "Red Bull Ring",
    "british-gp-setups": "Silverstone Circuit",
    "belgium-gp-setups": "Circuit de Spa-Francorchamps",
    "hungarian-gp-setups": "Hungaroring",
    "netherlands-gp-setups": "Zandvoort Circuit",
    "italian-gp-setups": "Autodromo Nazionale Monza",
    "madrid-gp-setups": "Madring",
    "azerbaijan-gp-setups": "Baku City Circuit",
    "singapore-gp-setups": "Marina Bay Street Circuit",
    "united-states-gp-setups": "Circuit of The Americas",
    "mexican-gp-setups": "Autódromo Hermanos Rodríguez",
    "brazilian-gp-setups": "Autódromo José Carlos Pace",
    "las-vegas-gp-setups": "Las Vegas Strip Circuit",
    "qatar-gp-setups": "Lusail International Circuit",
    "abu-dhabi-gp-setups": "Yas Marina Circuit",
}


class PartialCollectionError(RuntimeError):
    def __init__(self, failures: list[tuple[str, Exception]]) -> None:
        affected = ", ".join(
            f"{track}:{type(error).__name__}" for track, error in failures
        )
        super().__init__(f"{len(failures)} track collection failure(s): {affected}")
        self.failures = tuple(failures)


class SimRacingSetupF126Collector(SimRacingSetupCollector):
    """Collect public community and publicly accessible Pro F1 26 setups."""

    GameId = GameId.F1_26
    game_url: ClassVar[str] = SimRacingSetupCollector.base_url + "setups/f1-26/"

    def __init__(self) -> None:
        super().__init__()
        self._tracks: Dict[str, Dict[str, str]] = {}

    @staticmethod
    def _source_url(base_url: str, href: str) -> str | None:
        url = urljoin(base_url, href)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "simracingsetup.com":
            return None
        return url

    def _parse_tracks(self, html: str) -> Iterator[Dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            url = self._source_url(self.game_url, anchor["href"])
            if url is None:
                continue
            match = TRACK_PATH.match(urlparse(url).path)
            if not match or match.group(1) in seen:
                continue
            slug = match.group(1).lower()
            seen.add(slug)
            yield {
                "slug": slug,
                "circuit": TRACK_NAMES.get(
                    slug,
                    slug.removesuffix("-gp-setups").replace("-", " ").title(),
                ),
                "url": url,
            }

    def _parse_listing(self, html: str, base_url: str) -> Iterator[Dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        for row in soup.select("div.car-setup-archive-box-100"):
            anchor = row.find("a", href=True)
            if anchor is None:
                continue
            url = self._source_url(base_url, anchor["href"])
            if url is None or url in seen:
                continue
            path = urlparse(url).path
            community = COMMUNITY_SETUP_PATH.match(path)
            pro = PRO_SETUP_PATH.match(path)
            if not community and not pro:
                continue
            seen.add(url)
            car = row.select_one("span.team-name-color")
            yield {
                "kind": "pro" if pro else "community",
                "url": url,
                "id": (pro or community).group(1),
                "car": car.get_text(" ", strip=True) if car else "",
            }

    @staticmethod
    def _normalized(value: str) -> str:
        value = unicodedata.normalize("NFKC", value)
        return " ".join(value.replace(":", " ").split()).casefold()

    @staticmethod
    def _metadata(soup: BeautifulSoup) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for part in soup.select("div.car-setup-single-post-box div.listing-detail-part"):
            label = part.find("p")
            if label is None:
                continue
            key = " ".join(label.stripped_strings).casefold()
            if key == "conditions":
                value_node = part.find("span")
                value = value_node.get_text(" ", strip=True) if value_node else ""
            else:
                label.extract()
                value = " ".join(part.stripped_strings)
            result[key] = " ".join(value.split())
        return result

    def _parse_community_setup(
        self,
        html: str,
        url: str,
        source_id: str,
        track: Dict[str, str],
    ) -> Dict[str, Any] | None:
        soup = BeautifulSoup(html, "html.parser")
        sections = soup.select("div.setup-section")
        if not sections:
            return None
        settings: Dict[str, str] = {}
        for part in soup.select("div.setup-section div.setup-part-100"):
            name = part.select_one("div.setup-part-name")
            value = part.select_one("div.setup-part-number")
            if name is None or value is None:
                continue
            field = SETTING_LABELS.get(self._normalized(name.get_text(" ", strip=True)))
            if field:
                settings[field] = value.get_text(" ", strip=True)
        if not settings:
            return None

        metadata = self._metadata(soup)
        session = metadata.get("session type", "").removesuffix(" Setup").strip()
        weather = metadata.get("conditions", "").casefold() or None
        author = soup.select_one("span.author-name.fn")
        author_name = author.get_text(" ", strip=True) if author else ""
        author_name = re.sub(r"^Created by\s*", "", author_name, flags=re.I).strip()
        published = soup.select_one("time.entry-date.published")
        car = metadata.get("team") or None
        return self.mapper.map(
            {
                "id": source_id,
                "game": "F1 26",
                "circuit": track["circuit"],
                "car": car,
                "weather": weather,
                "url": url,
                "setup": {
                    "user": author_name or None,
                    "team": car,
                    "session": session or None,
                    "lap_time": metadata.get("lap time") or None,
                    "conditions": metadata.get("conditions") or None,
                    "date": published.get_text(" ", strip=True) if published else None,
                    "settings": settings,
                },
            }
        ).to_dict()

    @staticmethod
    def _pro_session(title: str) -> str:
        normalized = title.casefold()
        if "quali" in normalized:
            return "Qualifying"
        if "parc ferme" in normalized:
            return "Race & Qualifying"
        return "Race"

    def _parse_pro_setups(
        self,
        html: str,
        url: str,
        track: Dict[str, str],
        car: str | None,
    ) -> Iterator[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        page_text = " ".join(soup.stripped_strings)
        author_match = re.search(
            r"created by pro F1 sim racer ([^.]+)", page_text, re.I
        )
        author = author_match.group(1).strip() if author_match else "Sim Racing Setup Pro"
        pro_match = PRO_SETUP_PATH.match(urlparse(url).path)
        pro_slug = pro_match.group(1) if pro_match else track["slug"]

        for box in soup.select("div.car-setup-pro-box"):
            title_node = box.select_one("h3.setup-title")
            if title_node is None:
                continue
            title = title_node.get_text(" ", strip=True)
            settings: Dict[str, str] = {}
            descriptions: list[str] = []
            for group in box.select("div.setup-part-group"):
                group_title = group.select_one("span.setup-part-title")
                if group_title is None:
                    descriptions.append(" ".join(group.stripped_strings))
                    continue
                group_name = self._normalized(group_title.get_text(" ", strip=True))
                fields = PRO_GROUP_FIELDS.get(group_name)
                if fields:
                    values = [
                        value.get_text(" ", strip=True)
                        for value in group.select("li.setup-part-number")
                    ]
                    if len(values) == len(fields):
                        settings.update(zip(fields, values))
                else:
                    descriptions.append(" ".join(group.stripped_strings))
            if len(settings) != 20:
                continue

            description = " ".join(descriptions)
            lap_match = re.search(r"Reference Lap Time:\s*([0-9:.,]+)", description, re.I)
            date_match = re.search(
                r"Updated:\s*((?:[A-Za-z]+\s+\d{1,2},?|\d{1,2}\s+[A-Za-z]+)\s+\d{4})",
                description,
                re.I,
            )
            weather = "wet" if any(
                marker in title.casefold() for marker in ("wet", "intermediate")
            ) else "dry"
            title_slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
            yield self.mapper.map(
                {
                    "id": f"pro:{pro_slug}:{title_slug}",
                    "game": "F1 26",
                    "circuit": track["circuit"],
                    "car": car or None,
                    "weather": weather,
                    "url": url,
                    "setup": {
                        "user": author,
                        "team": car or None,
                        "session": self._pro_session(title),
                        "lap_time": lap_match.group(1).replace(",", ".") if lap_match else None,
                        "conditions": weather.title(),
                        "date": date_match.group(1) if date_match else None,
                        "notes": f"Pro setup: {title}",
                        "settings": settings,
                    },
                }
            ).to_dict()

    def get_tracks(self) -> List[str]:
        response = self.request_api(self.game_url, method="GET", json_response=False)
        if response is None:
            return []
        self._tracks = {track["slug"]: track for track in self._parse_tracks(response.text)}
        return list(self._tracks)

    def get_setups_by_track(self, track_name: str) -> List[Dict[str, Any]]:
        if track_name not in self._tracks:
            self.get_tracks()
        track = self._tracks.get(track_name)
        if track is None:
            raise ValueError(f"Unknown Sim Racing Setup track: {track_name}")
        response = self.request_api(track["url"], method="GET", json_response=False)
        if response is None:
            return []

        setups: List[Dict[str, Any]] = []
        for item in self._parse_listing(response.text, track["url"]):
            detail = self.request_api(item["url"], method="GET", json_response=False)
            if detail is None:
                continue
            if item["kind"] == "pro":
                setups.extend(
                    self._parse_pro_setups(
                        detail.text,
                        item["url"],
                        track,
                        item["car"] or None,
                    )
                )
            else:
                setup = self._parse_community_setup(
                    detail.text,
                    item["url"],
                    item["id"],
                    track,
                )
                if setup is not None:
                    setups.append(setup)
        return setups

    def run(self) -> Iterator[Dict[str, Any]]:
        tracks = self.get_tracks()
        failures: list[tuple[str, Exception]] = []
        if not tracks:
            return
        if COLLECTOR_CONCURRENCY <= 1:
            for track in tracks:
                try:
                    yield from self.get_setups_by_track(track)
                except Exception as error:
                    failures.append((track, error))
                    logger.exception("Sim Racing Setup track failed track=%s", track)
            if failures:
                raise PartialCollectionError(failures)
            return

        output: Queue[tuple[str, object]] = Queue()

        def collect(track: str) -> None:
            started = time.perf_counter()
            try:
                for setup in self.get_setups_by_track(track):
                    output.put(("item", setup))
                logger.info(
                    "Sim Racing Setup track finished track=%s duration=%.2fs",
                    track,
                    time.perf_counter() - started,
                )
            except Exception as error:
                output.put(("error", (track, error)))
                logger.exception("Sim Racing Setup track failed track=%s", track)
            finally:
                output.put(("done", track))

        with ThreadPoolExecutor(
            max_workers=min(COLLECTOR_CONCURRENCY, len(tracks)),
            thread_name_prefix="sim-racing-setup-track",
        ) as executor:
            futures = [executor.submit(collect, track) for track in tracks]
            completed = 0
            while completed < len(futures):
                kind, value = output.get()
                if kind == "item":
                    assert isinstance(value, dict)
                    yield value
                elif kind == "error":
                    assert isinstance(value, tuple)
                    failures.append(value)
                else:
                    completed += 1
        if failures:
            raise PartialCollectionError(failures)
