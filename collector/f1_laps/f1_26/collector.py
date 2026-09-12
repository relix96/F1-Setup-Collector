import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from queue import Queue
import time
from typing import Any, ClassVar, DefaultDict, Dict, Iterator, List
import unicodedata
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from collector.enums import GameId
from collector.f1_laps.mapper import F1SetupLapsMapper
from collector.f1_laps.f1_laps_collector import F1LapsCollector
from collector.f1_laps.utils.constants import DETAIL_LABELS, SETTING_LABELS
from collector.settings import COLLECTOR_CONCURRENCY
from collector.utils.logger import get_logger


TRACK_PATH = re.compile(r"/f1-\d+/setups/([a-z0-9_-]+)/?$", re.IGNORECASE)
SETUP_PATH = re.compile(
    r"/f1-\d+/setups/([^/]+)/([0-9a-f]{8}-[0-9a-f-]{27,})/?$", re.IGNORECASE
)
LEADERBOARD_LAP_PATH = re.compile(
    r"/f1-\d+/leaderboard/([^/]+)/([0-9a-f]{8}-[0-9a-f-]{27,})/?$",
    re.IGNORECASE,
)
logger = get_logger(__name__)


class PartialCollectionError(RuntimeError):
    """Raised after every unaffected track has finished."""

    def __init__(self, failures: list[tuple[str, str, Exception]]) -> None:
        affected = ", ".join(
            f"{track}/{weather}:{type(error).__name__}"
            for track, weather, error in failures
        )
        super().__init__(
            f"{len(failures)} track/weather collection failure(s): {affected}"
        )
        self.failures = tuple(failures)


class F1LapsF126Collector(F1LapsCollector):
    """Collect every F1Laps setup, ordered by track and dry/wet condition."""
    GameId = GameId.F1_26
    game_url: ClassVar[str] = F1LapsCollector.base_url + "f1-26/setups/"
    leaderboard_url: ClassVar[str] = (
        F1LapsCollector.base_url + "f1-26/leaderboard/"
    )
    telemetry_game_id: ClassVar[str] = "f12026"

    def __init__(self) -> None:
        super().__init__()
        self.mapper = F1SetupLapsMapper()
        self._tracks: Dict[str, Dict[str, str]] = {}
        self._leaderboards: Dict[str, List[Dict[str, Any]]] = {}

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
            # ``wet`` is the global weather filter, not a circuit. Current
            # F1Laps circuit slugs also use underscores (for example,
            # ``saudi_arabia`` and ``las_vegas``).
            if slug == "wet" or not re.fullmatch(r"[a-z0-9_-]+", slug):
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

    @staticmethod
    def _normalized(value: Any) -> str:
        if value is None:
            return ""
        normalized = unicodedata.normalize("NFKC", str(value))
        return " ".join(normalized.split()).casefold()

    @staticmethod
    def _lap_time_ms(value: Any) -> int | None:
        match = re.fullmatch(
            r"(?:(\d+):)?(\d{1,2})\.(\d{3})",
            str(value or "").strip(),
        )
        if not match:
            return None
        minutes = int(match.group(1) or 0)
        return (minutes * 60 + int(match.group(2))) * 1000 + int(match.group(3))

    @staticmethod
    def _date_key(value: Any) -> str:
        text = " ".join(str(value or "").replace(".", "").split())
        for date_format in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(text, date_format).date().isoformat()
            except ValueError:
                continue
        return text.casefold()

    def _parse_leaderboard(
        self,
        html: str,
        base_url: str,
    ) -> Iterator[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        for row in soup.select("tbody tr"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 7:
                continue
            anchor = cells[2].find("a", href=True)
            if anchor is None:
                continue
            url = urljoin(base_url, anchor["href"])
            match = LEADERBOARD_LAP_PATH.search(urlparse(url).path)
            if match is None or url in seen:
                continue
            flags = " ".join(cells[6].stripped_strings)
            if "has telemetry data" not in flags.casefold():
                continue
            seen.add(url)
            conditions_match = re.search(
                r"\b(dry|wet)\s+conditions\b",
                flags,
                re.IGNORECASE,
            )
            yield {
                "id": match.group(2),
                "url": url,
                "date": " ".join(cells[1].stripped_strings),
                "lap_time": " ".join(cells[2].stripped_strings),
                "user": " ".join(cells[3].stripped_strings),
                "team": " ".join(cells[4].stripped_strings),
                "session": " ".join(cells[5].stripped_strings),
                "conditions": (
                    conditions_match.group(1).title()
                    if conditions_match is not None
                    else None
                ),
            }

    def _get_leaderboard(self, track_name: str) -> List[Dict[str, Any]]:
        if track_name in self._leaderboards:
            return self._leaderboards[track_name]

        url = urljoin(self.leaderboard_url, f"{track_name}/")
        try:
            response = self.request_api(url, method="GET", json_response=False)
            entries = (
                list(self._parse_leaderboard(response.text, url))
                if response is not None
                else []
            )
        except Exception as error:
            logger.warning(
                "Leaderboard unavailable track=%s error_type=%s",
                track_name,
                type(error).__name__,
            )
            entries = []
        self._leaderboards[track_name] = entries
        return entries

    def _matching_lap(
        self,
        setup: Dict[str, Any],
        candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any] | None:
        details = setup.get("setup") or {}
        lap_time_ms = self._lap_time_ms(details.get("lap_time"))
        if not self._normalized(details.get("user")) or lap_time_ms is None:
            return None

        expected = {
            "user": self._normalized(details.get("user")),
            "team": self._normalized(details.get("team")),
            "session": self._normalized(details.get("session")),
            "conditions": self._normalized(
                details.get("conditions") or setup.get("weather")
            ),
            "date": self._date_key(details.get("date")),
        }
        matches = []
        for candidate in candidates:
            if self._lap_time_ms(candidate.get("lap_time")) != lap_time_ms:
                continue
            actual = {
                "user": self._normalized(candidate.get("user")),
                "team": self._normalized(candidate.get("team")),
                "session": self._normalized(candidate.get("session")),
                "conditions": self._normalized(candidate.get("conditions")),
                "date": self._date_key(candidate.get("date")),
            }
            # Every context field emitted by both F1Laps pages must agree.
            if all(
                expected[field] and expected[field] == actual[field]
                for field in expected
            ):
                matches.append(candidate)
        return matches[0] if len(matches) == 1 else None

    def _parse_lap_details(self, html: str) -> Dict[str, Any]:
        strings = self._strings(html)
        labels = {
            "Time": "lap_time",
            "Sector 1": "sector_1",
            "Sector 2": "sector_2",
            "Sector 3": "sector_3",
            **DETAIL_LABELS,
        }
        details = self._pairs(strings, labels)
        try:
            heading = next(text for text in strings if text.startswith("Lap by "))
            details["user"] = heading.removeprefix("Lap by ").strip()
        except StopIteration:
            pass
        return details

    def _attach_telemetry(
        self,
        setup: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> None:
        lap_url = candidate["url"]
        try:
            detail_response = self.request_api(
                lap_url,
                method="GET",
                json_response=False,
            )
            if detail_response is None:
                return
            lap_details = self._parse_lap_details(detail_response.text)
            if self._matching_lap(
                setup,
                [{**candidate, **lap_details}],
            ) is None:
                return

            telemetry_url = urljoin(
                self.base_url,
                f"laptimes/{self.telemetry_game_id}/{candidate['id']}/telemetry_charts/",
            )
            payload = self.request_api(telemetry_url, method="GET")
            original = (
                payload.get("original") if isinstance(payload, dict) else None
            )
            if not isinstance(original, dict) or not original:
                return
            setup["setup"]["telemetry"] = {
                "match": {
                    "method": "exact_user_lap_time_and_context",
                    "leaderboard_lap_id": candidate["id"],
                    "leaderboard_url": lap_url,
                },
                "lap": {
                    key: lap_details.get(key)
                    for key in ("lap_time", "sector_1", "sector_2", "sector_3")
                },
                "data": original,
                "is_2026_regulations": bool(
                    payload.get("is_2026_regulations", False)
                ),
            }
        except Exception as error:
            logger.warning(
                "Telemetry unavailable leaderboard_lap_id=%s error_type=%s",
                candidate.get("id", "unknown"),
                type(error).__name__,
            )

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

    def get_setups(
        self,
        track_name: str,
        weather: str,
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

        leaderboard = self._get_leaderboard(track_name)
        for setup_url in self._parse_listing(listing.text, listing_url):
            detail = self.request_api(setup_url, method="GET", json_response=False)
            if detail is None:
                continue
            raw = self._parse_setup(detail.text, setup_url, track, weather)
            matching_lap = self._matching_lap(raw, leaderboard)
            if matching_lap is not None:
                self._attach_telemetry(raw, matching_lap)
            yield self.mapper.map(raw).to_dict()

    def get_setups_by_track(self, track_name: str) -> List[Dict[str, Any]]:
        """Return all dry and wet setups from one track."""
        if not re.fullmatch(r"[a-z0-9_-]+", track_name):
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

    def _collect_track_resiliently(
        self,
        track_name: str,
        failures: list[tuple[str, str, Exception]],
    ) -> Iterator[Dict[str, Any]]:
        started_at = time.perf_counter()
        collected = 0
        failure_count_before = len(failures)
        logger.info("Track collection started track=%s", track_name)
        for weather in ("dry", "wet"):
            try:
                for setup in self.get_setups(track_name, weather):
                    collected += 1
                    yield setup
            except Exception as error:
                failures.append((track_name, weather, error))
                logger.error(
                    "event=collector_error collector=f1_laps_f1_26 "
                    "source=f1_laps game=f1_26 scope=track run_id=%s track=%s "
                    "weather=%s error_type=%s",
                    self.collector_run_id or "unknown",
                    track_name,
                    weather,
                    type(error).__name__,
                    exc_info=(type(error), error, error.__traceback__),
                )
        track_failures = len(failures) - failure_count_before
        logger.info(
            "Track collection finished track=%s status=%s records=%d "
            "failures=%d duration=%.2fs",
            track_name,
            "partial" if track_failures else "success",
            collected,
            track_failures,
            time.perf_counter() - started_at,
        )

    def run(self) -> Iterator[Dict[str, Any]]:
        tracks = self.get_tracks()
        if not tracks:
            return
        failures: list[tuple[str, str, Exception]] = []
        if COLLECTOR_CONCURRENCY <= 1:
            for track_name in tracks:
                yield from self._collect_track_resiliently(track_name, failures)
            if failures:
                raise PartialCollectionError(failures)
            return

        output: Queue[tuple[str, object]] = Queue()

        def collect_track(track_name: str) -> None:
            track_failures: list[tuple[str, str, Exception]] = []
            try:
                for setup in self._collect_track_resiliently(
                    track_name,
                    track_failures,
                ):
                    output.put(("item", setup))
            except Exception as error:
                track_failures.append((track_name, "unknown", error))
                logger.error(
                    "event=collector_error collector=f1_laps_f1_26 "
                    "source=f1_laps game=f1_26 scope=track_worker run_id=%s track=%s "
                    "weather=unknown error_type=%s",
                    self.collector_run_id or "unknown",
                    track_name,
                    type(error).__name__,
                    exc_info=(type(error), error, error.__traceback__),
                )
            finally:
                for failure in track_failures:
                    output.put(("error", failure))
                output.put(("done", track_name))

        with ThreadPoolExecutor(
            max_workers=min(COLLECTOR_CONCURRENCY, len(tracks)),
            thread_name_prefix="f1laps-track",
        ) as executor:
            futures = [executor.submit(collect_track, track) for track in tracks]
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

    def collect_organized(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """Return ``{country: {dry: [...], wet: [...]}}`` for JSON export/storage."""
        grouped: DefaultDict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
            lambda: {"dry": [], "wet": []}
        )
        for item in self.run():
            country = item["setup"].pop("country", item["circuit"])
            grouped[country][item["weather"]].append(item)
        return dict(grouped)
