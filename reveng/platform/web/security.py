"""Local-only HTTP request boundary for the RevEng control center."""
from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_TEST_HOSTS = frozenset({"testserver"})
_TEST_CLIENTS = frozenset({"testclient"})


def _is_loopback_name(value: str) -> bool:
    candidate = value.strip().strip("[]").casefold()
    if candidate in _LOOPBACK_HOSTS:
        return True
    try:
        return ip_address(candidate).is_loopback
    except ValueError:
        return False


def _authority_from_host(value: str) -> tuple[str, int | None] | None:
    try:
        parsed = urlsplit(f"//{value}")
        if not parsed.hostname:
            return None
        return parsed.hostname.casefold(), parsed.port
    except ValueError:
        return None


def _authority_from_url(value: str) -> tuple[str, int | None] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        return parsed.hostname.casefold(), parsed.port
    except ValueError:
        return None


def _same_local_authority(value: str, request_authority: tuple[str, int | None]) -> bool:
    candidate = _authority_from_url(value)
    if candidate is None:
        return False
    candidate_host, candidate_port = candidate
    request_host, request_port = request_authority
    return (
        _is_loopback_name(candidate_host)
        and candidate_host == request_host
        and candidate_port == request_port
    ) or (
        candidate_host in _TEST_HOSTS
        and candidate_host == request_host
        and candidate_port == request_port
    )


class LocalRequestGuardMiddleware:
    """Reject non-loopback hosts, remote peers, and cross-origin mutations.

    This is a local application boundary, not user authentication. Requests from
    local non-browser processes remain possible by design; authored Python code
    has a separate explicit opt-in gate.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").casefold(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        host_value = headers.get("host", "")
        request_authority = _authority_from_host(host_value)
        if request_authority is None or not (
            _is_loopback_name(request_authority[0])
            or request_authority[0] in _TEST_HOSTS
        ):
            await PlainTextResponse("RevEng accepts only local Host headers.", status_code=403)(
                scope, receive, send
            )
            return

        client = scope.get("client")
        client_host = str(client[0]) if client else ""
        if client_host and not (
            _is_loopback_name(client_host) or client_host in _TEST_CLIENTS
        ):
            await PlainTextResponse("RevEng accepts only loopback clients.", status_code=403)(
                scope, receive, send
            )
            return

        method = str(scope.get("method", "GET")).upper()
        if method not in _SAFE_METHODS:
            if headers.get("sec-fetch-site", "").casefold() == "cross-site":
                await PlainTextResponse("Cross-site mutation rejected.", status_code=403)(
                    scope, receive, send
                )
                return

            origin = headers.get("origin")
            if origin and not _same_local_authority(origin, request_authority):
                await PlainTextResponse("Cross-origin mutation rejected.", status_code=403)(
                    scope, receive, send
                )
                return

            referer = headers.get("referer")
            if not origin and referer and not _same_local_authority(referer, request_authority):
                await PlainTextResponse("Cross-origin mutation rejected.", status_code=403)(
                    scope, receive, send
                )
                return

        await self.app(scope, receive, send)


__all__ = ["LocalRequestGuardMiddleware"]
