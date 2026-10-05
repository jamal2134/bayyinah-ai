import asyncio
import time
from abc import ABC, abstractmethod

import httpx

from app.models.evidence import EvidenceProvider
from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult, QueryAttempt
from app.retrieval.cache import MemoryCache


class ProviderAdapter(ABC):
    provider: EvidenceProvider

    def __init__(self, base_url: str, client: httpx.AsyncClient, cache: MemoryCache,
                 max_attempts: int = 3, max_concurrency: int = 2):
        self.base_url = base_url.rstrip("/")
        self.client = client
        self.cache = cache
        self.max_attempts = max_attempts
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def get_json(self, path: str, params: dict | None = None, headers: dict | None = None):
        payload, _ = await self.get_json_response(path, params, headers)
        return payload

    async def get_json_response(self, path: str, params: dict | None = None,
                                headers: dict | None = None):
        params = params or {}
        key = self.cache.key(self.provider.value, path, params)
        cached = await self.cache.get(key)
        if cached is not None:
            return cached, 200
        async with self.semaphore:
            response = await self.client.get(f"{self.base_url}{path}", params=params, headers=headers)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidProviderResponse("provider returned invalid JSON") from exc
        await self.cache.set(key, payload)
        return payload, response.status_code

    def failure(self, exc: Exception, attempts: list[QueryAttempt]) -> ProviderResult:
        error_type, retryable = ProviderErrorType.PROVIDER_ERROR, False
        if isinstance(exc, httpx.TimeoutException):
            error_type, retryable = ProviderErrorType.TIMEOUT, True
        elif isinstance(exc, httpx.NetworkError):
            error_type, retryable = ProviderErrorType.NETWORK_ERROR, True
        elif isinstance(exc, httpx.HTTPStatusError):
            if exc.response.status_code == 429:
                error_type, retryable = ProviderErrorType.RATE_LIMIT, True
            elif exc.response.status_code == 403:
                error_type = ProviderErrorType.ACCESS_DENIED
            elif exc.response.status_code == 404:
                error_type = ProviderErrorType.ENDPOINT_UNAVAILABLE
        elif isinstance(exc, InvalidProviderResponse):
            error_type = ProviderErrorType.INVALID_RESPONSE
        return ProviderResult(provider=self.provider, success=False, query_attempts=attempts,
                              error=ProviderError(provider=self.provider, error_type=error_type,
                                                  message=("Provider API rejected the request." if error_type == ProviderErrorType.ACCESS_DENIED
                                                           else str(exc)),
                                                  retryable=retryable,
                                                  http_status=(exc.response.status_code
                                                               if isinstance(exc, httpx.HTTPStatusError) else None)))

    @staticmethod
    def attempt(query: str | None, number: int, started: float, count: int, success: bool,
                endpoint: str | None = None, http_status: int | None = None,
                parameters: dict | None = None, parser_success: bool | None = None):
        return QueryAttempt(query=query, attempt=number,
                            duration_ms=round((time.perf_counter() - started) * 1000, 2),
                            result_count=count, success=success, endpoint=endpoint,
                            http_status=http_status, parameters=parameters or {},
                            parser_success=parser_success)

    @abstractmethod
    async def retrieve(self, claim): ...


class InvalidProviderResponse(ValueError):
    pass

