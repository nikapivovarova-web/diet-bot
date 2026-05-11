from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable, Iterator, MutableMapping, MutableSet
from dataclasses import dataclass
from typing import Generic, TypeVar


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")
_NO_PROTECTED_KEY = object()


@dataclass
class _CacheEntry(Generic[V]):
    value: V
    last_seen: float


class BoundedTTLDict(MutableMapping[K, V]):
    """Small LRU/TTL mapping with a soft cap.

    The cap is soft when an evictable predicate is provided and all old entries
    are currently protected by it.
    """

    def __init__(
        self,
        *,
        max_size: int,
        ttl_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        evictable: Callable[[V], bool] | None = None,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._monotonic = monotonic
        self._evictable = evictable
        self._data: OrderedDict[K, _CacheEntry[V]] = OrderedDict()

    @property
    def max_size(self) -> int:
        return self._max_size

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    def __getitem__(self, key: K) -> V:
        now = self._monotonic()
        entry = self._data[key]
        if self._is_expired(entry, now) and self._can_evict(entry.value):
            del self._data[key]
            raise KeyError(key)
        entry.last_seen = now
        self._data.move_to_end(key)
        return entry.value

    def __setitem__(self, key: K, value: V) -> None:
        now = self._monotonic()
        self._purge_expired(now)
        self._data[key] = _CacheEntry(value=value, last_seen=now)
        self._data.move_to_end(key)
        self._evict_overflow(protected_key=key)

    def __delitem__(self, key: K) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[K]:
        self.prune()
        return iter(self._data)

    def __len__(self) -> int:
        self.prune()
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        now = self._monotonic()
        entry = self._data.get(key)  # type: ignore[arg-type]
        if entry is None:
            return False
        if self._is_expired(entry, now) and self._can_evict(entry.value):
            del self._data[key]  # type: ignore[index]
            return False
        entry.last_seen = now
        self._data.move_to_end(key)  # type: ignore[arg-type]
        return True

    def clear(self) -> None:
        self._data.clear()

    def prune(self) -> None:
        now = self._monotonic()
        self._purge_expired(now)
        self._evict_overflow()

    def _is_expired(self, entry: _CacheEntry[V], now: float) -> bool:
        return now - entry.last_seen >= self._ttl_seconds

    def _can_evict(self, value: V) -> bool:
        return self._evictable is None or self._evictable(value)

    def _purge_expired(self, now: float) -> None:
        while True:
            victim = self._first_expired_evictable_key(now)
            if victim is None:
                return
            del self._data[victim]

    def _first_expired_evictable_key(self, now: float) -> K | None:
        for key, entry in self._data.items():
            if not self._is_expired(entry, now):
                return None
            if self._can_evict(entry.value):
                return key
        return None

    def _evict_overflow(self, *, protected_key: object = _NO_PROTECTED_KEY) -> None:
        while len(self._data) > self._max_size:
            victim = self._first_evictable_key(protected_key=protected_key)
            if victim is None:
                return
            del self._data[victim]

    def _first_evictable_key(self, *, protected_key: object = _NO_PROTECTED_KEY) -> K | None:
        for key, entry in self._data.items():
            if protected_key is not _NO_PROTECTED_KEY and key == protected_key:
                continue
            if self._can_evict(entry.value):
                return key
        return None


class BoundedTTLSet(MutableSet[K]):
    def __init__(
        self,
        *,
        max_size: int,
        ttl_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._items: BoundedTTLDict[K, None] = BoundedTTLDict(
            max_size=max_size,
            ttl_seconds=ttl_seconds,
            monotonic=monotonic,
        )

    @property
    def max_size(self) -> int:
        return self._items.max_size

    @property
    def ttl_seconds(self) -> float:
        return self._items.ttl_seconds

    def __contains__(self, value: object) -> bool:
        return value in self._items

    def __iter__(self) -> Iterator[K]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def add(self, value: K) -> None:
        self._items[value] = None

    def discard(self, value: K) -> None:
        self._items.pop(value, None)

    def clear(self) -> None:
        self._items.clear()

    def prune(self) -> None:
        self._items.prune()
