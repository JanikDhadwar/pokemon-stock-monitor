"""Proxy pool: round-robin rotation over proxies from the PROXIES env var."""
import itertools
import os
from typing import Dict, List, Optional


class ProxyPool:
    """Loads ``PROXIES`` (comma-separated ``http://user:pass@host:port``).

    A single rotating endpoint from a provider works fine too — just put the
    one URL in. :meth:`get` cycles round-robin; :meth:`as_dict` returns the
    ``requests``-style proxies mapping. Empty pool = direct connection.
    """

    def __init__(self, proxies: Optional[str] = None):
        raw = proxies if proxies is not None else os.getenv("PROXIES", "")
        self.proxies: List[str] = [p.strip() for p in raw.split(",") if p.strip()]
        self._cycle = itertools.cycle(self.proxies) if self.proxies else None

    def __len__(self) -> int:
        return len(self.proxies)

    def get(self) -> Optional[str]:
        """Next proxy URL, or None when no proxies are configured."""
        return next(self._cycle) if self._cycle else None

    def as_dict(self, proxy: Optional[str] = None) -> Dict[str, str]:
        p = proxy or self.get()
        return {"http": p, "https": p} if p else {}
