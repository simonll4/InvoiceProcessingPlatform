"""Simple cache for LLM responses to reduce API calls."""

import hashlib
import json
import time
from typing import Any, Optional


class ResponseCache:
    """Simple in-memory cache for LLM responses with lightweight metadata."""

    def __init__(self, ttl_seconds: int = 300):  # 5 minutes default
        """
        Initialize cache.

        Args:
            ttl_seconds: Time-to-live for cache entries (default: 300s = 5min)
        """
        self.cache: dict[str, dict[str, Any]] = {}
        self.ttl = ttl_seconds

    def _generate_key(self, question: str) -> str:
        """Generate cache key from normalized question text."""
        normalized = question.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(
        self,
        question: str,
        fingerprint: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Return cached entry if available and optionally fingerprint-matched."""
        key = self._generate_key(question)
        entry = self.cache.get(key)

        if not entry:
            return None

        timestamp = entry.get("timestamp", 0.0)
        if time.time() - timestamp >= self.ttl:
            # Expired entry cleanup
            del self.cache[key]
            return None

        cached_fingerprint = entry.get("metadata", {}).get("fingerprint")
        if fingerprint and cached_fingerprint and fingerprint != cached_fingerprint:
            # Avoid serving mismatched cache entries when fingerprint differs
            return None

        return entry

    def set(
        self,
        question: str,
        answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store answer alongside optional metadata."""
        key = self._generate_key(question)
        self.cache[key] = {
            "answer": answer,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }

    def clear(self):
        """Clear all cache entries."""
        self.cache.clear()

    def cleanup_expired(self) -> int:
        """
        Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        now = time.time()
        expired_keys = [
            key
            for key, entry in self.cache.items()
            if now - entry.get("timestamp", 0.0) >= self.ttl
        ]

        for key in expired_keys:
            del self.cache[key]

        return len(expired_keys)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        now = time.time()
        valid_entries = sum(
            1
            for entry in self.cache.values()
            if now - entry.get("timestamp", 0.0) < self.ttl
        )

        return {
            "total_entries": len(self.cache),
            "valid_entries": valid_entries,
            "expired_entries": len(self.cache) - valid_entries,
            "ttl_seconds": self.ttl,
        }
