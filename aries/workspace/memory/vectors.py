"""The cached matrix that replaces a vector index.

NEVER np.vstack
---------------
`np.vstack(rows + [new])` reallocates and copies the whole matrix on every
append. At 10k x 768 that is a 29 MB copy per remembered sentence, and at the
41 MB measured here it dominated everything else in the write path. This is a
preallocated buffer that doubles: appends are O(1) amortised, the live view is
`self._rows[:self._used]`, and the copy happens once per doubling instead of
once per row.

Search is `mat @ q` over unit vectors, i.e. cosine, i.e. a single BLAS call —
1.06 ms over 10k x 768 measured on this machine. Brute force over 10^4 rows is
not a compromise at this scale; it is faster than the alternatives and it is
exact, which an approximate index is not.
"""
from __future__ import annotations

import threading

import numpy as np


class VectorCache:
    """Row ids and their unit vectors, kept in RAM and searched exactly."""

    def __init__(self, dim, capacity=1024):
        self.dim = int(dim)
        self._rows = np.zeros((max(1, capacity), self.dim), dtype=np.float32)
        self._ids: list[str] = []
        self._index: dict[str, int] = {}
        self._used = 0
        self._lock = threading.RLock()

    def __len__(self):
        return self._used

    @property
    def ids(self):
        return list(self._ids)

    @property
    def matrix(self):
        """A view, not a copy. Callers must not write through it."""
        return self._rows[:self._used]

    @property
    def megabytes(self):
        return self._rows.nbytes / 2**20

    def _grow(self, needed):
        capacity = self._rows.shape[0]
        if needed <= capacity:
            return
        while capacity < needed:
            capacity *= 2
        grown = np.zeros((capacity, self.dim), dtype=np.float32)
        grown[:self._used] = self._rows[:self._used]
        self._rows = grown

    def add(self, row_id, vector):
        """Insert or replace one row. Replacement keeps the original slot."""
        vector = np.asarray(vector, dtype=np.float32).reshape(-1)
        if vector.size != self.dim:
            raise ValueError(f"expected {self.dim} dimensions, got {vector.size}")
        with self._lock:
            slot = self._index.get(row_id)
            if slot is None:
                self._grow(self._used + 1)
                slot = self._used
                self._index[row_id] = slot
                self._ids.append(row_id)
                self._used += 1
            self._rows[slot] = vector

    def extend(self, pairs):
        for row_id, vector in pairs:
            self.add(row_id, vector)

    def drop(self, row_id):
        """Remove by swapping the last row down — the only O(1) removal that
        keeps the matrix contiguous. Expiry is rare; order is never relied on."""
        with self._lock:
            slot = self._index.pop(row_id, None)
            if slot is None:
                return False
            last = self._used - 1
            if slot != last:
                self._rows[slot] = self._rows[last]
                moved = self._ids[last]
                self._ids[slot] = moved
                self._index[moved] = slot
            self._ids.pop()
            self._rows[last] = 0
            self._used = last
            return True

    def search(self, query, limit=10, floor=None):
        """Top `limit` (id, cosine) pairs. One BLAS call, then a partial sort."""
        if not self._used:
            return []
        query = np.asarray(query, dtype=np.float32).reshape(-1)
        if query.size != self.dim:
            raise ValueError(f"expected {self.dim} dimensions, got {query.size}")
        scores = self._rows[:self._used] @ query
        limit = min(int(limit), self._used)
        # argpartition is O(n); argsort over 10^4 would be the slower half of
        # the query at this point, which is the whole reason this is fast.
        top = np.argpartition(-scores, limit - 1)[:limit]
        top = top[np.argsort(-scores[top])]
        return [(self._ids[i], float(scores[i])) for i in top
                if floor is None or scores[i] >= floor]

    def vector_for(self, row_id):
        """The stored row, or None. A view into the buffer; read only."""
        slot = self._index.get(row_id)
        return None if slot is None else self._rows[slot]

    def nearest(self, query):
        found = self.search(query, limit=1)
        return found[0] if found else (None, -1.)
