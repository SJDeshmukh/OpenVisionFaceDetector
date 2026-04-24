"""
Per-vendor metric learning via triplet-loss-trained linear projection.

Algorithm overview
------------------
Given N registered people each with K augmented embeddings (already stored in
person_embeddings), we learn a linear map  W: R^512 → R^256  such that:

  - same-person embeddings cluster tightly   (small intra-class cosine distance)
  - different-person embeddings push apart   (large inter-class cosine distance)

Training uses *hard negative mining*: for each (anchor, positive) pair from the
same person, the negative is the *closest* different-person embedding in the
current projected space.  This directly targets the most confusing pairs
(far-away / blurry faces that look similar).

The projection W is saved to disk per vendor and loaded into the embedding
cache at inference time.  Retraining is triggered asynchronously (background
thread) after any registration change.

No new packages required — pure numpy + Python stdlib.
"""

from __future__ import annotations

import os
import time
import threading
import logging
from collections import defaultdict

import numpy as np

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "metric_models")
os.makedirs(_MODEL_DIR, exist_ok=True)

INPUT_DIM        = 512    # ArcFace embedding dimension
PROJ_DIM         = 256    # projected dimension (halved for speed + regularisation)
MARGIN           = 0.30   # triplet margin (cosine-distance units)
N_EPOCHS         = 150    # max training epochs
LR               = 5e-4   # Adam base learning rate
MAX_TRIPLETS     = 800    # cap on hard-mined triplets per epoch
MIN_PERSONS      = 3      # minimum distinct people needed before training
MIN_EMBS_PERSON  = 2      # minimum augmented embeddings per person
PATIENCE         = 25     # early-stop patience (epochs without improvement)
L2_REG           = 1e-4   # weight-decay regularisation on W
LOSS_SAMPLE_N    = 200    # how many triplets to sample for loss estimation


# ── Per-vendor serialised training lock ───────────────────────────────────────

_LOCK_GUARD: threading.Lock = threading.Lock()
_VENDOR_LOCKS: dict[int, threading.Lock] = {}


def _get_lock(vendor_id: int) -> threading.Lock:
    with _LOCK_GUARD:
        if vendor_id not in _VENDOR_LOCKS:
            _VENDOR_LOCKS[vendor_id] = threading.Lock()
        return _VENDOR_LOCKS[vendor_id]


# ── Math helpers ──────────────────────────────────────────────────────────────

def _l2(X: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation.  Safe against zero vectors."""
    if X.ndim == 1:
        n = float(np.linalg.norm(X))
        return X / n if n > 1e-10 else X
    n = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.maximum(n, 1e-10)


def project(W: np.ndarray, X: np.ndarray) -> np.ndarray:
    """
    Linear projection followed by L2 normalisation.

    W : (PROJ_DIM, INPUT_DIM)
    X : (N, INPUT_DIM)  or  (INPUT_DIM,)
    Returns: (N, PROJ_DIM)  or  (PROJ_DIM,)  — unit-norm rows.
    """
    scalar = X.ndim == 1
    if scalar:
        X = X.reshape(1, -1)
    out = _l2(X.astype(np.float32) @ W.T)   # (N, PROJ_DIM)
    return out[0] if scalar else out


# ── Adam optimiser (pure numpy) ───────────────────────────────────────────────

class _Adam:
    def __init__(
        self,
        shape: tuple,
        lr: float = LR,
        b1: float = 0.9,
        b2: float = 0.999,
        eps: float = 1e-8,
    ) -> None:
        self.lr, self.b1, self.b2, self.eps = lr, b1, b2, eps
        self.m = np.zeros(shape, dtype=np.float32)
        self.v = np.zeros(shape, dtype=np.float32)
        self.t = 0

    def step(self, g: np.ndarray) -> np.ndarray:
        self.t += 1
        self.m = self.b1 * self.m + (1.0 - self.b1) * g
        self.v = self.b2 * self.v + (1.0 - self.b2) * (g * g)
        m_hat = self.m / (1.0 - self.b1 ** self.t)
        v_hat = self.v / (1.0 - self.b2 ** self.t)
        return self.lr * m_hat / (np.sqrt(v_hat) + self.eps)


# ── Hard triplet mining ───────────────────────────────────────────────────────

def _mine_hard_triplets(
    X_proj: np.ndarray,
    y: np.ndarray,
    max_n: int = MAX_TRIPLETS,
) -> list[tuple[int, int, int]]:
    """
    For each anchor a (embedding from person i):

      positive p  — farthest same-person embedding in current projected space
                    (hardest positive: maximally different augmented view of the
                    same person, forcing the model to pull it in)

      negative n  — closest different-person embedding
                    (hardest negative: the pair currently most likely to be
                    confused — far-away faces that look similar)

    Only active triplets (loss > 0) are returned.
    """
    # Full N×N cosine-similarity matrix via batch matmul (fast with BLAS)
    S = (X_proj @ X_proj.T).astype(np.float64)   # (N, N), range [-1, 1]

    triplets: list[tuple[int, int, int]] = []
    for pid in np.unique(y):
        pos_idx = np.where(y == pid)[0]
        neg_idx = np.where(y != pid)[0]
        if len(pos_idx) < 2 or len(neg_idx) == 0:
            continue

        for a_i in pos_idx:
            # Hardest positive: lowest similarity among same-person embeddings
            p_sims = S[a_i, pos_idx].copy()
            p_sims[pos_idx == a_i] = 2.0   # exclude self with sentinel
            p_i = int(pos_idx[np.argmin(p_sims)])

            # Hardest negative: highest similarity among different-person embeddings
            n_i = int(neg_idx[np.argmax(S[a_i, neg_idx])])

            # Only keep if active: sim_an − sim_ap + margin > 0
            if float(S[a_i, n_i]) - float(S[a_i, p_i]) + MARGIN > 0:
                triplets.append((a_i, p_i, n_i))

    np.random.shuffle(triplets)
    return triplets[:max_n]


# ── Analytical gradient ───────────────────────────────────────────────────────

def _triplet_gradient(
    W: np.ndarray,
    X: np.ndarray,
    triplets: list[tuple[int, int, int]],
) -> tuple[np.ndarray, int]:
    """
    Compute the mean gradient of the triplet margin loss w.r.t. W.

    Loss (per active triplet) with cosine distance d = 1 − cos_sim:
        L = max(0,  d(W·a, W·p)  −  d(W·a, W·n)  + margin)
          = max(0,  sim_an  −  sim_ap  +  margin)

    Full derivation for sim_xy = dot( normalize(Wx), normalize(Wy) ):

        ∂sim_xy/∂W  via x  =  outer( (ŷ − sim_xy·x̂) / ‖Wx‖ ,  x )
        ∂sim_xy/∂W  via y  =  outer( (x̂ − sim_xy·ŷ) / ‖Wy‖ ,  y )

    Since ∂L/∂sim_ap = −1  and  ∂L/∂sim_an = +1:

        ∂L/∂W  =  ∂sim_an/∂W  −  ∂sim_ap/∂W

    Returns (grad, n_active_triplets).
    """
    G = np.zeros_like(W, dtype=np.float64)
    active = 0

    for a_i, p_i, n_i in triplets:
        za = W @ X[a_i]
        zp = W @ X[p_i]
        zn = W @ X[n_i]

        nza = float(np.linalg.norm(za))
        nzp = float(np.linalg.norm(zp))
        nzn = float(np.linalg.norm(zn))
        if nza < 1e-10 or nzp < 1e-10 or nzn < 1e-10:
            continue

        ha = za / nza
        hp = zp / nzp
        hn = zn / nzn

        sim_ap = float(ha @ hp)
        sim_an = float(ha @ hn)

        if sim_an - sim_ap + MARGIN <= 0.0:
            continue   # inactive (projection changed since mining)
        active += 1

        # ── ∂sim_ap/∂W ──────────────────────────────────────────────────────
        # via anchor   a : (hp − sim_ap·ha) / nza  ⊗  a
        # via positive p : (ha − sim_ap·hp) / nzp  ⊗  p
        d_ap_a = (hp - sim_ap * ha) / nza
        d_ap_p = (ha - sim_ap * hp) / nzp

        # ── ∂sim_an/∂W ──────────────────────────────────────────────────────
        # via anchor   a : (hn − sim_an·ha) / nza  ⊗  a
        # via negative n : (ha − sim_an·hn) / nzn  ⊗  n
        d_an_a = (hn - sim_an * ha) / nza
        d_an_n = (ha - sim_an * hn) / nzn

        # ∂L/∂W = (∂sim_an − ∂sim_ap) / ∂W
        # Combine anchor contributions (appears in both terms)
        G += np.outer(d_an_a - d_ap_a, X[a_i])
        G += np.outer(-d_ap_p,          X[p_i])
        G += np.outer(d_an_n,           X[n_i])

    if active > 0:
        G /= active  # mean gradient over active triplets

    return G.astype(np.float32), active


# ── Training entry point ──────────────────────────────────────────────────────

def train_projection(
    embeddings_by_person: dict,
    n_epochs: int = N_EPOCHS,
    warm_W: np.ndarray | None = None,
) -> np.ndarray | None:
    """
    Learn W: (PROJ_DIM, INPUT_DIM) from stored per-person embeddings.

    Parameters
    ----------
    embeddings_by_person
        {person_id: list_of_np.ndarray(512,)}  — unit-norm embeddings.
    n_epochs
        Maximum training epochs (early stopping may terminate earlier).
    warm_W
        Optional starting W for a warm restart from the previous trained weights.

    Returns
    -------
    W (float32, shape PROJ_DIM × INPUT_DIM) on success, None if insufficient data.
    """
    # ── Filter persons with enough embeddings ───────────────────────────────
    valid: dict[int, np.ndarray] = {}
    for pid, embs in embeddings_by_person.items():
        arr = [e for e in embs if e is not None and np.array(e).size == INPUT_DIM]
        if len(arr) >= MIN_EMBS_PERSON:
            valid[pid] = np.array(arr, dtype=np.float32)

    n_persons = len(valid)
    if n_persons < MIN_PERSONS:
        logger.info(
            f"[Metric] Skip: {n_persons} qualified people < {MIN_PERSONS} required"
        )
        return None

    # ── Build flat arrays ────────────────────────────────────────────────────
    all_embs: list[np.ndarray] = []
    all_labels: list[int] = []
    for pid, embs in valid.items():
        for e in embs:
            all_embs.append(e)
            all_labels.append(int(pid))

    X = _l2(np.array(all_embs, dtype=np.float32))  # (N, 512) unit-norm
    y = np.array(all_labels)
    N = len(X)
    logger.info(f"[Metric] Training: {n_persons} people, {N} embeddings total")

    # ── Initialise W ────────────────────────────────────────────────────────
    if warm_W is not None and warm_W.shape == (PROJ_DIM, INPUT_DIM):
        W = warm_W.copy().astype(np.float32)
        logger.info("[Metric] Warm restart from previous W")
    else:
        # PCA initialisation: eigen-decompose the INPUT_DIM × INPUT_DIM covariance
        # matrix so we always get PROJ_DIM principal directions regardless of how
        # many embeddings (N) are in the gallery.
        # Using X.T @ X (shape INPUT_DIM × INPUT_DIM) guarantees Vt is at least
        # (INPUT_DIM, INPUT_DIM) → Vt[:PROJ_DIM] is always (PROJ_DIM, INPUT_DIM).
        try:
            cov = (X.astype(np.float64).T @ X.astype(np.float64)) / max(N, 1)
            _, _, Vt = np.linalg.svd(cov)          # Vt: (INPUT_DIM, INPUT_DIM)
            W = Vt[:PROJ_DIM].astype(np.float32)   # always (PROJ_DIM, INPUT_DIM)
            assert W.shape == (PROJ_DIM, INPUT_DIM)
            logger.info("[Metric] PCA (covariance) initialisation")
        except Exception:
            rng = np.random.default_rng(42)
            M = rng.standard_normal((PROJ_DIM, INPUT_DIM)).astype(np.float32)
            U, _, _ = np.linalg.svd(M, full_matrices=False)
            W = U
            logger.info("[Metric] Random-orthogonal initialisation (PCA failed)")

    opt    = _Adam((PROJ_DIM, INPUT_DIM))
    best_W = W.copy()
    best_loss  = float("inf")
    stall_cnt  = 0

    for epoch in range(n_epochs):
        # Project with current W and mine hard triplets
        X_proj   = project(W, X)                                    # (N, PROJ_DIM)
        triplets = _mine_hard_triplets(X_proj, y, MAX_TRIPLETS)

        if not triplets:
            logger.info(f"[Metric] Epoch {epoch}: no active triplets → converged")
            break

        # Compute analytical gradient
        G, n_active = _triplet_gradient(W, X, triplets)

        if n_active == 0:
            stall_cnt += 1
            if stall_cnt >= PATIENCE:
                break
            continue

        # Estimate mean loss on a random sample (cheap approximation)
        S = X_proj @ X_proj.T
        sample = triplets[: min(LOSS_SAMPLE_N, len(triplets))]
        loss_vals = [
            max(0.0, float(S[ai, ni]) - float(S[ai, pi]) + MARGIN)
            for ai, pi, ni in sample
        ]
        epoch_loss = sum(loss_vals) / max(len(loss_vals), 1)

        # Guard: skip malformed or NaN/Inf gradient
        if G.shape != W.shape or not np.isfinite(G).all():
            logger.warning(
                f"[Metric] Epoch {epoch}: bad gradient "
                f"shape={G.shape} finite={np.isfinite(G).all()} — skipping"
            )
            stall_cnt += 1
            if stall_cnt >= PATIENCE:
                break
            continue

        # L2 regularisation (prevents W from growing unboundedly)
        G = G + L2_REG * W

        # Adam parameter update
        W = W - opt.step(G)

        # Track best W
        if epoch_loss < best_loss - 1e-6:
            best_loss  = epoch_loss
            best_W     = W.copy()
            stall_cnt  = 0
        else:
            stall_cnt += 1
            if stall_cnt >= PATIENCE:
                logger.info(
                    f"[Metric] Early stop at epoch {epoch} "
                    f"(patience={PATIENCE}), best loss={best_loss:.4f}"
                )
                break

        if epoch % 30 == 0:
            logger.info(
                f"[Metric] Epoch {epoch:3d} | loss={epoch_loss:.4f} "
                f"| active={n_active}/{len(triplets)}"
            )

    logger.info(f"[Metric] Training complete.  Best loss: {best_loss:.4f}")
    return best_W


# ── Centroid builder ──────────────────────────────────────────────────────────

def build_proj_centroids(W: np.ndarray, items: list) -> dict[int, np.ndarray]:
    """
    Compute per-person centroids in the projected embedding space.

    For each person we project all their stored embeddings through W, average
    the projections, and re-normalise.  The centroid is a compressed, stable
    representation of a person that tolerates augmentation variance.

    Parameters
    ----------
    W     : (PROJ_DIM, INPUT_DIM) trained projection matrix.
    items : list of cache dicts with keys 'person_id' and 'vec'.

    Returns
    -------
    {person_id: unit-norm centroid (PROJ_DIM,)}
    """
    buckets: dict[int, list[np.ndarray]] = defaultdict(list)
    for it in items:
        pid = int(it["person_id"])
        v = it.get("vec")
        if v is not None and v.size == INPUT_DIM:
            buckets[pid].append(v.astype(np.float32))

    centroids: dict[int, np.ndarray] = {}
    for pid, vecs in buckets.items():
        stacked = np.array(vecs, dtype=np.float32)    # (k, INPUT_DIM)
        proj    = project(W, stacked)                  # (k, PROJ_DIM), unit-norm rows
        c       = proj.mean(axis=0)
        n       = float(np.linalg.norm(c))
        centroids[pid] = (c / n).astype(np.float32) if n > 1e-10 else c

    return centroids


# ── Persistence ───────────────────────────────────────────────────────────────

def _model_path(vendor_id: int) -> str:
    return os.path.join(_MODEL_DIR, f"v{int(vendor_id)}_W.npy")


def save_projection(vendor_id: int, W: np.ndarray) -> None:
    try:
        np.save(_model_path(vendor_id), W.astype(np.float32))
        logger.info(f"[Metric] Saved W for vendor {vendor_id}")
    except Exception as e:
        logger.warning(f"[Metric] Could not save W for vendor {vendor_id}: {e}")


def load_projection(vendor_id: int) -> np.ndarray | None:
    path = _model_path(vendor_id)
    if not os.path.exists(path):
        return None
    try:
        W = np.load(path).astype(np.float32)
        if W.ndim == 2 and W.shape == (PROJ_DIM, INPUT_DIM):
            return W
        logger.warning(
            f"[Metric] Shape mismatch for vendor {vendor_id}: "
            f"expected ({PROJ_DIM},{INPUT_DIM}), got {W.shape}"
        )
    except Exception as e:
        logger.warning(f"[Metric] Failed to load W for vendor {vendor_id}: {e}")
    return None


def delete_projection(vendor_id: int) -> None:
    try:
        p = _model_path(vendor_id)
        if os.path.exists(p):
            os.remove(p)
            logger.info(f"[Metric] Deleted W for vendor {vendor_id}")
    except Exception:
        pass


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_embeddings_from_db(vendor_id: int) -> dict[int, list[np.ndarray]] | None:
    """
    Load all stored embeddings for a vendor from person_embeddings.
    Returns {person_id: [unit-norm_vec, ...]} or None on failure.
    """
    try:
        from utils import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "SELECT person_id, vec, dim FROM person_embeddings WHERE vendor_id = ?",
            (int(vendor_id),),
        )
        rows = c.fetchall() or []
        conn.close()
    except Exception as e:
        logger.warning(f"[Metric] DB load failed for vendor {vendor_id}: {e}")
        return None

    buckets: dict[int, list[np.ndarray]] = defaultdict(list)
    for r in rows:
        try:
            pid = int(r[0])
            vb  = r[1]
            dim = int(r[2])
            if not vb or dim != INPUT_DIM:
                continue
            v = np.frombuffer(vb, dtype=np.float32).copy()
            if v.size != dim:
                continue
            n = float(np.linalg.norm(v))
            if n > 1e-10:
                buckets[pid].append((v / n).astype(np.float32))
        except Exception:
            continue

    return dict(buckets) if buckets else None


def _bust_vendor_cache(vendor_id: int) -> None:
    """Invalidate in-memory cache so next request rebuilds with the new W."""
    try:
        from utils import _VENDOR_EMB_CACHE
        prefix = f"{int(vendor_id)}_"
        to_del = [k for k in list(_VENDOR_EMB_CACHE.keys()) if str(k).startswith(prefix)]
        for k in to_del:
            _VENDOR_EMB_CACHE.pop(k, None)
        if to_del:
            logger.info(f"[Metric] Cache busted for vendor {vendor_id} ({len(to_del)} keys)")
    except Exception:
        pass


# ── Background retraining ─────────────────────────────────────────────────────

def retrain_for_vendor(vendor_id: int) -> None:
    """
    Load embeddings from DB, train W, save to disk, bust embedding cache.

    This is intended to run in a daemon thread.  Concurrent calls for the
    same vendor are serialised via a per-vendor lock — if a retrain is already
    in progress the duplicate call returns immediately.
    """
    vid  = int(vendor_id)
    lock = _get_lock(vid)

    if not lock.acquire(blocking=False):
        logger.info(f"[Metric] Retrain for vendor {vid} already running — skipping duplicate")
        return

    try:
        t0   = time.time()
        embs = _load_embeddings_from_db(vid)
        if not embs:
            logger.info(f"[Metric] No embeddings found for vendor {vid}")
            return

        # Warm restart: if a previous W exists start from it (faster convergence)
        warm = load_projection(vid)

        W = train_projection(embs, warm_W=warm)
        if W is not None:
            save_projection(vid, W)
            _bust_vendor_cache(vid)
            logger.info(f"[Metric] Vendor {vid} retrained in {time.time() - t0:.1f}s")
        else:
            logger.info(f"[Metric] Vendor {vid}: not enough data — projection not updated")
    except Exception as e:
        logger.error(f"[Metric] retrain_for_vendor({vid}) failed: {e}", exc_info=True)
    finally:
        lock.release()


def schedule_retrain(vendor_id: int, delay: float = 3.0) -> None:
    """
    Fire-and-forget: debounced async retrain for this vendor.

    The `delay` lets rapid successive registration calls (e.g. batch commit of
    30 students) settle before we start training so we train once on the full
    dataset rather than 30 partial times.
    """
    if not vendor_id:
        return

    def _run() -> None:
        time.sleep(delay)
        retrain_for_vendor(int(vendor_id))

    t = threading.Thread(
        target=_run,
        daemon=True,
        name=f"metric-retrain-v{int(vendor_id)}",
    )
    t.start()
