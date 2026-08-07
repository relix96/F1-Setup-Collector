import csv
import io
from typing import Any, ClassVar, Iterator, List, Optional

from collector.base_collector import BaseCollector
from collector.enums import GameId, SourceId
from collector.excel_file.mapper import ExcelFileF126Mapper


class ExcelFileF126Collector(BaseCollector):
    """Collect F1 26 setups from the configured public Google Sheet tab."""

    GameId = GameId.F1_26
    SourceId = SourceId.EXCEL_FILE

    spreadsheet_url: ClassVar[str] = ("https://docs.google.com/spreadsheets/d/1fUZKqMpARGJ1XEvsmGlOtN2_NVPOqLehPNiLH-YyYSI/edit?pli=1&gid=2082870794#gid=2082870794")
    csv_url: ClassVar[str] = ("https://docs.google.com/spreadsheets/d/1fUZKqMpARGJ1XEvsmGlOtN2_NVPOqLehPNiLH-YyYSI/export?format=csv&gid=2082870794")
    expected_headers: ClassVar[tuple[str, ...]] = (
        "Circuit",
        "Aero",
        "Differential",
        "Susp. geometry",
        "Suspension",
        "Brakes",
        "Tires Q",
        "Tires R",
        "Compounds",
        "Strategy (50%)",
        "Laps 50%",
        "Creation date",
        "Notes",
    )
    def __init__(self) -> None:
        super().__init__()
        self.mapper = ExcelFileF126Mapper(self.spreadsheet_url)
        self._rows: Optional[List[dict[str, str]]] = None
        self._tire_temperatures: list[dict[str, str]] = []
        self._engine_temperatures: list[dict[str, str]] = []

    @staticmethod
    def _reference_rows(
        rows: list[list[str]],
        title: str,
        field_names: tuple[str, ...],
    ) -> list[dict[str, str]]:
        """Read a small table whose title and data are in the first columns."""
        try:
            title_index = next(
                index
                for index, row in enumerate(rows)
                if row and row[0].strip() == title
            )
        except StopIteration:
            return []

        result: list[dict[str, str]] = []
        # The row immediately after the title contains the display headers.
        for row in rows[title_index + 2 :]:
            values = [cell.strip() for cell in row]
            if not values or not values[0]:
                break
            padded = values + [""] * (len(field_names) - len(values))
            result.append(dict(zip(field_names, padded)))
        return result

    def _download_rows(self) -> list[dict[str, str]]:
        response = self.request_api(self.csv_url, method="GET", json_response=False)
        if response is None:
            return []

        # The first row is an advisory message; locate the actual table header.
        all_rows = list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
        for header_index, row in enumerate(all_rows):
            if row and row[0].strip() == "Circuit":
                headers = tuple(cell.strip() for cell in row)
                break
        else:
            raise ValueError("The spreadsheet does not contain a Circuit header")

        if headers[: len(self.expected_headers)] != self.expected_headers:
            raise ValueError("The spreadsheet setup columns have changed")

        setups: list[dict[str, str]] = []
        for row in all_rows[header_index + 1 :]:
            values = [cell.strip() for cell in row]
            if not values or not values[0]:
                break
            padded = values + [""] * (len(headers) - len(values))
            setups.append(dict(zip(headers, padded)))

        self._tire_temperatures = self._reference_rows(
            all_rows,
            "Tire Temperatures",
            ("Compound", "Temp Range (°C)", "Temp Range (°F)"),
        )
        self._engine_temperatures = self._reference_rows(
            all_rows,
            "Engine temperatures",
            ("Temp (°C)", "Temp (°F)", "Power %"),
        )
        return setups

    def _get_rows(self) -> list[dict[str, str]]:
        if self._rows is None:
            self._rows = self._download_rows()
        return self._rows

    def get_tracks(self) -> list[str]:
        return [row["Circuit"] for row in self._get_rows()]

    def get_setups_by_track(self, track_name: str) -> list[dict[str, Any]]:
        normalized = track_name.strip().casefold()
        return [
            self.mapper.map(row).to_dict()
            for row in self._get_rows()
            if row["Circuit"].casefold() == normalized
        ]

    def get_tire_temperatures(self) -> list[dict[str, str]]:
        """Return the recommended temperature ranges for every tire compound."""
        self._get_rows()
        return self.mapper.map_tire_temperatures(self._tire_temperatures)

    def get_engine_temperatures(self) -> list[dict[str, str]]:
        """Return the engine temperature-to-power reference table."""
        self._get_rows()
        return self.mapper.map_engine_temperatures(self._engine_temperatures)

    def get_reference_data(self) -> dict[str, list[dict[str, str]]]:
        """Return all auxiliary reference tables from the spreadsheet."""
        self._get_rows()
        return self.mapper.map_reference_data(
            self._tire_temperatures, self._engine_temperatures
        )

    def run(self) -> Iterator[dict[str, Any]]:
        for row in self._get_rows():
            yield self.mapper.map(row).to_dict()
        yield from self.get_tire_temperatures()
        yield from self.get_engine_temperatures()
