import asyncio
import copy
import json
from typing import Any


class MemoryCache:
    def __init__(self):
        self._values: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def key(provider: str, operation: str, parameters: dict) -> str:
        return f"{provider}:{operation}:{json.dumps(parameters, sort_keys=True, ensure_ascii=False)}"

    async def get(self, key: str):
        async with self._lock:
            value = self._values.get(key)
            return copy.deepcopy(value)

    async def set(self, key: str, value):
        async with self._lock:
            self._values[key] = copy.deepcopy(value)

