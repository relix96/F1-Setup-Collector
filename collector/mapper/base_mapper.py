from abc import ABC, abstractmethod
from typing import Any, Dict

from collector.models.setup import SetupDTO


class BaseMapper(ABC):
    @abstractmethod
    def map(self, item: Dict[str, Any]) -> SetupDTO:
        """Convert a website-specific item into the common setup model."""
