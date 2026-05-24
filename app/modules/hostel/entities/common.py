from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True, slots=True)
class HostelEntity:
    entity_type: str
    prefix: str

    @property
    def query(self) -> Dict[str, Any]:
        return {"_meta.entity_type": self.entity_type}

