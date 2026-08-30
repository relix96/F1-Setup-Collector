from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class ExcelSetup:
    source: str
    source_id: str
    game: Optional[str] = None
    circuit: Optional[str] = None
    weather: Optional[str] = None
    setup: Optional[Dict[str, Any]] = None
    source_url: Optional[str] = None
    collector_date: Optional[str] = None
    

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
