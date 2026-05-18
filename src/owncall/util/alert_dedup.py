"""Alert deduplication to avoid redundant LLM investigations.

Normalises alert summaries by stripping digits (timestamps, metric values,
firing counts) and hashing the result.  Alerts that produce the same
fingerprint within a configurable TTL window are considered duplicates.
"""

from __future__ import annotations

import hashlib
import re
import time


class AlertDeduplicator:
    """In-memory, per-channel TTL cache for alert fingerprints."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[str, float] = {}  # key -> monotonic timestamp

    def is_duplicate(self, summary: str, channel: str) -> bool:
        """Return True if a similar alert was already seen within the TTL."""
        self._evict_expired()
        key = self._cache_key(summary, channel)
        return key in self._cache

    def record(self, summary: str, channel: str) -> None:
        """Record an alert so future similar alerts are detected as duplicates."""
        key = self._cache_key(summary, channel)
        if key not in self._cache:
            self._cache[key] = time.monotonic()

    def _cache_key(self, summary: str, channel: str) -> str:
        return f"{channel}:{self._fingerprint(summary)}"

    def _fingerprint(self, summary: str) -> str:
        normalized = re.sub(r"\d+", "", summary)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, ts in self._cache.items() if now - ts > self._ttl]
        for k in expired:
            del self._cache[k]
