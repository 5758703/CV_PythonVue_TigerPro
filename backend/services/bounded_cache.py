"""Small thread-safe LRU for heavyweight model instances."""
from collections import OrderedDict
from collections.abc import MutableMapping
from threading import RLock


class BoundedCache(MutableMapping):
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._items = OrderedDict()
        self._lock = RLock()

    def __getitem__(self, key):
        with self._lock:
            value = self._items[key]
            self._items.move_to_end(key)
            return value

    def __setitem__(self, key, value):
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            if len(self._items) > self.capacity:
                self._items.popitem(last=False)

    def __delitem__(self, key):
        with self._lock:
            del self._items[key]

    def __iter__(self):
        with self._lock:
            return iter(list(self._items))

    def __len__(self):
        with self._lock:
            return len(self._items)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def clear(self):
        with self._lock:
            self._items.clear()
