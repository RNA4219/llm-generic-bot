from typing import Any, Dict, Optional, Protocol

class Sender(Protocol):
    async def send(self, text: str, channel: Optional[str] = None, *, job: str) -> None: ...

class Job(Protocol):
    name: str
    priority: int
    async def run(self, ctx: Dict[str, Any]) -> Optional[str]: ...
