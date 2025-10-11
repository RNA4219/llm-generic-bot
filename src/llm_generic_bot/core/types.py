from typing import Protocol, Iterable, Optional, Dict, Any

class Sender(Protocol):
    async def send(self, text: str, channel: Optional[str] = None) -> None: ...

class Job(Protocol):
    name: str
    priority: int
    async def run(self, ctx: Dict[str, Any]) -> Optional[str]: ...
