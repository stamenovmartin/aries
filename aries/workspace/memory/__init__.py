"""Semantic memory — §14's missing layer.

ARIES decides for itself what was worth keeping out of what the user said,
writes it down unasked, and uses it later. Four modules:

    embedding.py   text -> a unit vector, behind an interface with two backends
    vectors.py     the cached float32 matrix that IS the index
    extraction.py  the three-stage cascade that decides what to keep
    store.py       the write path, where the layer rule is enforced
    migration.py   the explicit ALTER TABLE this project has no alembic for

WHY THERE IS NO VECTOR INDEX
----------------------------
Measured on this machine, 2026-09-24 and again here: a cached normalised
float32 matrix multiplied by the query (`mat @ q`) beats sqlite-vec by 21x at
768 dimensions and 10k rows, and by 61x at 1024/1k. Reading the blobs back out
of SQLite per query costs 64 ms against 1.0 ms for the cached matrix, so the
in-RAM cache is not an optimisation on top of the design — it is the design.
10k x 768 float32 is 29 MB.

WHY OPENBLAS IS PINNED TO ONE THREAD
------------------------------------
A 1 ms matrix-vector product does not need twelve cores, and the cores are
wanted by speech recognition, which is on the latency path and this is not.
The variable is read by OpenBLAS when numpy is first imported, so it is set
here, at the top, before anything in this package pulls numpy in.
"""
import os

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from aries.workspace.memory.store import (  # noqa: E402
    conclusions, expire, forget, observe, observe_later, remember, utterances, warm,
)

__all__ = ["conclusions", "expire", "forget", "observe", "observe_later",
           "remember", "utterances", "warm"]
