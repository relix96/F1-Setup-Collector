from typing import ClassVar

from collector.base_collector import BaseCollector
from collector.enums import SourceId
from collector.sim_racing_setup.mapper import SimRacingSetupMapper


class SimRacingSetupCollector(BaseCollector):
    SourceId = SourceId.SIM_RACING_SETUP
    ProxySupported = True
    base_url: ClassVar[str] = "https://simracingsetup.com/"

    def __init__(self) -> None:
        super().__init__()
        self.mapper = SimRacingSetupMapper()
