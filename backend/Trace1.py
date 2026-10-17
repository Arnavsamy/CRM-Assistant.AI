import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class RequestTrace:
    request_id: str = field(default_factory=lambda: str(uuid4()))
    search_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: float = field(default_factory=time.time)
    events: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        await self.events.put({"event": event, "data": data})

    async def close(self) -> None:
        await self.events.put(None)
