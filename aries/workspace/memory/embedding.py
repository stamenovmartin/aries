"""Text to a unit vector, behind an interface with room for two models.

WHICH MODEL, AND WHY
--------------------
`intfloat/multilingual-e5-base`, MIT, 279 MB as int8 ONNX, 768 dimensions.
Measured Macedonian retrieval on MMTEB `mkd_Cyrl` is nDCG@10 = 90.4. LaBSE,
despite its reputation as the multilingual sentence model, scores 68.8 — the
worst credible option. `google/embeddinggemma` scores 82.0 and ships under a
restrictive licence. `BAAI/bge-m3` scores 92.9 and is one `ollama pull` away,
so both are reachable through `get()` and the experiment runs whichever it is
given; nothing above the interface knows which one answered.

THE PREFIXES ARE NOT OPTIONAL
-----------------------------
e5 was trained with `query: ` and `passage: ` in front of the text and loses
several points when they are omitted. Getting this wrong is silent — the
vectors still look fine — so the prefix is applied here, in one place, and
`kind` is a required argument rather than a defaulted one.

NO TORCH
--------
sentence-transformers pulls 2-3 GB of torch for an inference graph this machine
can run in 279 MB. `tokenizers` and `onnxruntime` were already in the virtual
environment; that is the whole dependency.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from aries.intelligence.providers import loopback_url
from aries.workspace.memory.local_transport import open_local

ROOT = Path(__file__).resolve().parents[3]
E5_DIR = ROOT / "var" / "models" / "multilingual-e5-base"
OLLAMA = os.environ.get("ARIES_OLLAMA", "http://127.0.0.1:11434")
DEFAULT = "e5-base-int8"


class EmbedderUnavailable(RuntimeError):
    """The model is not on this machine. Callers degrade; they never guess."""


class _Embedder:
    name = ""
    dim = 0

    def encode(self, texts, *, kind):
        raise NotImplementedError

    def query(self, text):
        return self.encode([text], kind="query")[0]

    def passages(self, texts):
        return self.encode(list(texts), kind="passage")


class OnnxE5(_Embedder):
    """multilingual-e5-base, int8 ONNX, CPU only.

    CPU only is a constraint, not a preference: about 2.5 GB of VRAM is free
    once faster-whisper large-v3 has loaded, and speech recognition has the
    stronger claim on it.
    """

    name = "e5-base-int8"
    dim = 768
    PREFIX = {"query": "query: ", "passage": "passage: "}

    def __init__(self, directory=E5_DIR, threads=4, max_tokens=256):
        graph, vocabulary = Path(directory) / "model_int8.onnx", Path(directory) / "tokenizer.json"
        if not graph.exists() or not vocabulary.exists():
            raise EmbedderUnavailable(f"run ./scripts/aries-fetch-embedder — {graph} is absent")
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self._tokenizer = Tokenizer.from_file(str(vocabulary))
        # 512 is the model's limit; 256 is this application's. A remembered
        # utterance that needs more than 256 XLM-R tokens is a transcript, not a
        # memory, and truncating costs less than embedding it would.
        self._tokenizer.enable_truncation(max_length=max_tokens)
        self._tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(threads)
        options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(graph), options, providers=["CPUExecutionProvider"])
        self._lock = threading.Lock()

    def encode(self, texts, *, kind):
        """One sequence per graph call. MEASURED HERE, NOT ASSUMED.

        This model is DYNAMICALLY quantised: the int8 scales for each activation
        tensor are computed at run time from that tensor, and a padded batch
        changes the tensor, so it changes the scales, so it changes the answer.
        Measured on this machine: `play some music.` embedded alone and embedded
        in a batch of 45 differ by cosine 0.947, and hidden states at the real
        token positions drift 13% relative. Masking is honoured — an all-ones
        mask is three times worse — this is quantisation, not attention.

        A vector that depends on what else was in the batch is a vector that
        cannot be compared with one stored earlier, which is the whole job. So
        the batch is a loop. It costs about 1.6x throughput (7.5 ms per text
        against 4.7 ms at batch 16) and buys an embedding that is a function of
        its text alone. The fp32 graph does not have this property; if the batch
        cost ever matters, that is the lever.
        """
        prefix = self.PREFIX[kind]
        encoded = self._tokenizer.encode_batch([prefix + (t or "") for t in texts])
        pooled = np.empty((len(encoded), self.dim), dtype=np.float32)
        with self._lock:                        # one ORT session, many callers
            for row, item in enumerate(encoded):
                length = sum(item.attention_mask) or len(item.ids)
                ids = np.array([item.ids[:length]], dtype=np.int64)
                mask = np.ones_like(ids)
                hidden = self._session.run(None, {"input_ids": ids, "attention_mask": mask})[0]
                # Mean pooling over real tokens, then L2. e5's own pooling;
                # cosine then reduces to a dot product, which is what makes
                # `mat @ q` the search.
                pooled[row] = hidden[0].mean(axis=0)
        return (pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)).astype(np.float32)


class OllamaEmbedder(_Embedder):
    """Whatever `ollama pull` provided — bge-m3 by default.

    bge-m3 was trained without instruction prefixes, so `kind` is accepted and
    ignored rather than silently prepending something the model never saw.
    """

    name = "bge-m3-ollama"
    dim = 1024

    def __init__(self, model="bge-m3", endpoint=OLLAMA, timeout=60):
        try:
            endpoint=loopback_url(endpoint)
        except ValueError:
            raise EmbedderUnavailable('Memory embedding requires a literal loopback endpoint') from None
        self._model, self._endpoint, self._timeout = model, endpoint, timeout
        try:
            tags = self._get("/api/tags")
        except OSError as exc:
            raise EmbedderUnavailable(f"ollama is not answering at {endpoint}: {exc}") from None
        if not any(m.get("name", "").split(":")[0] == model.split(":")[0] for m in tags.get("models", [])):
            raise EmbedderUnavailable(f"ollama has no {model} — run: ollama pull {model}")
        self.name = f"{model}-ollama"

    def _get(self, path):
        with open_local(self._endpoint + path, timeout=self._timeout) as response:
            return json.loads(response.read())

    def encode(self, texts, *, kind):
        body = json.dumps({"model": self._model, "input": list(texts)}).encode()
        request = urllib.request.Request(self._endpoint + "/api/embed", data=body,
                                         headers={"Content-Type": "application/json"})
        try:
            with open_local(request, timeout=self._timeout) as response:
                payload = json.loads(response.read())
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise EmbedderUnavailable(str(exc)) from None
        vectors = np.asarray(payload["embeddings"], dtype=np.float32)
        self.dim = vectors.shape[1]
        return vectors / np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9, None)


BACKENDS = {"e5-base-int8": OnnxE5, "bge-m3-ollama": OllamaEmbedder}
_cache: dict[str, _Embedder] = {}
_cache_lock = threading.Lock()


def get(name=DEFAULT, **kwargs):
    """One loaded model per name per process. Loading e5 costs ~0.8 s."""
    if name not in BACKENDS:
        raise EmbedderUnavailable(f"unknown embedder {name!r}; have {sorted(BACKENDS)}")
    with _cache_lock:
        if name not in _cache or kwargs:
            embedder = BACKENDS[name](**kwargs)
            if kwargs:
                return embedder                 # a tuned instance is not the shared one
            _cache[name] = embedder
        return _cache[name]


def available(name=DEFAULT):
    try:
        get(name)
        return True
    except (EmbedderUnavailable, Exception):    # noqa: BLE001 — a broken model is an absent model
        return False


def pack(vector):
    return np.asarray(vector, dtype=np.float32).tobytes()


def unpack(blob, dim=None):
    vector = np.frombuffer(blob, dtype=np.float32)
    return vector if dim is None or vector.size == dim else None
