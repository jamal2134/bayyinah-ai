import asyncio
import hashlib
import threading
import time

import requests

from app.models.retrieval import ProviderError, ProviderErrorType, ProviderResult, QueryAttempt


def stable_token(*parts: object, length: int = 20) -> str:
    value = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


async def run_serialized(lock: threading.Lock, function, *args, **kwargs):
    def call():
        with lock:
            return function(*args, **kwargs)
    return await asyncio.to_thread(call)


def attempt(query, started, count, success, *, parameters=None, endpoint=None):
    return QueryAttempt(
        query=query, attempt=1, duration_ms=round((time.perf_counter() - started) * 1000, 2),
        result_count=count, success=success, endpoint=endpoint,
        parameters=parameters or {}, parser_success=success,
    )


def requests_failure(provider, exc: Exception, attempts: list[QueryAttempt]) -> ProviderResult:
    error_type, retryable, status = ProviderErrorType.PROVIDER_ERROR, False, None
    if isinstance(exc, requests.Timeout):
        error_type, retryable = ProviderErrorType.TIMEOUT, True
    elif isinstance(exc, requests.ConnectionError):
        error_type, retryable = ProviderErrorType.NETWORK_ERROR, True
    elif isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 429:
            error_type, retryable = ProviderErrorType.RATE_LIMIT, True
        elif status == 403:
            error_type = ProviderErrorType.ACCESS_DENIED
        elif status == 404:
            error_type = ProviderErrorType.ENDPOINT_UNAVAILABLE
    elif isinstance(exc, requests.RequestException):
        error_type, retryable = ProviderErrorType.NETWORK_ERROR, True
    return ProviderResult(
        provider=provider, success=False, query_attempts=attempts,
        error=ProviderError(provider=provider, error_type=error_type,
                            message=str(exc) or type(exc).__name__, retryable=retryable,
                            http_status=status),
    )
