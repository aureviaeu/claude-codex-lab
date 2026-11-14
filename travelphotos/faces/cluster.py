"""Group detected faces so the owner can tick people instead of preparing photos."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# Faces whose similarity to a group's average is at least this join the group.
# Stricter than matching.MATCH so one group is rarely two people.
JOIN = 0.45


@dataclass
class Cluster:
    id: int
    members: list[int]  # indexes into the face list given to cluster_faces
    centroid: list[float] = field(default_factory=list)


def cluster_faces(embeddings: list[list[float]], join: float = JOIN) -> list[Cluster]:
    """Greedy grouping, largest groups first. Deterministic for the same input."""
    if not embeddings:
        return []
    vecs = np.asarray(embeddings, dtype="float64")
    sums: list[np.ndarray] = []
    members: list[list[int]] = []
    cents = np.zeros((0, vecs.shape[1]))
    for i, v in enumerate(vecs):
        if len(members):
            sims = cents @ v
            best = int(np.argmax(sims))
            if sims[best] >= join:
                members[best].append(i)
                sums[best] = sums[best] + v
                c = sums[best] / (np.linalg.norm(sums[best]) or 1.0)
                cents[best] = c
                continue
        members.append([i])
        sums.append(v.copy())
        cents = np.vstack([cents, v / (np.linalg.norm(v) or 1.0)])
    order = sorted(range(len(members)), key=lambda k: (-len(members[k]), members[k][0]))
    return [Cluster(id=n + 1, members=members[k], centroid=cents[k].tolist()) for n, k in enumerate(order)]
