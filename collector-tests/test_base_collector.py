from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import pytest

from collector.base_collector import BaseCollector
from collector.enums import GameId as GameIdEnum
from collector.enums import SourceId as SourceIdEnum


class DummyCollector(BaseCollector):
    GameId = GameIdEnum.F1_26
    SourceId = SourceIdEnum.F1_LAPS

    def run(self):
        return iter(())

    def get_setups_by_track(self, track_name: str):
        return []

    def get_tracks(self):
        return []

    def test_base_collector_accepts_enum_ids() -> None:
    with patch(
        "collector.base_collector.HttpScrapper.__init__",
        return_value=None,
    ):
        collector = DummyCollector()

    assert collector.GameId is GameIdEnum.F1_26
    assert collector.SourceId is SourceIdEnum.F1_LAPS
