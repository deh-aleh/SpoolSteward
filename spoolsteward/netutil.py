"""Network helpers shared by the portal, the IPP gateway and the scanner proxy."""

from fastapi import Request


def client_ip(request: Request) -> str:
    """The address of the direct peer ("?" if the server can not tell)."""
    return request.client.host if request.client else "?"


def public_host(request: Request, scheme: str = "https") -> str:
    """The Host the client used, always with its port.

    A browser leaves :443 (or :80) out of the Host header, but CUPS and most IPP clients read an
    ipps:// address without a port as 631, so the addresses we hand out must spell the port.
    """
    host = request.headers.get("host", "localhost")
    if host.endswith("]") or ":" not in host:                  # no port (a bare name or a bare IPv6 literal)
        return f"{host}:{443 if scheme in ('https', 'ipps') else 80}"
    return host
