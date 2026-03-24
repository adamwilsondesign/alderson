"""
LEAKPHANTOM v2.3.1 — Correlation Engine
Bayesian posterior updates, Union-Find clustering, incremental Louvain.
Cross-protocol identity correlation through probabilistic linking.
"""

import math
import time
from collections import defaultdict
from typing import Optional

from utils import LeakStore, GraphNode, GraphEdge, logger


# ---------------------------------------------------------------------------
# Union-Find (Disjoint Set) for cluster management
# ---------------------------------------------------------------------------
class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}
        self.size: dict[str, int] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
            self.size[x] = 1
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])  # path compression
        return self.parent[x]

    def union(self, x: str, y: str) -> str:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return rx
        # Union by rank
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        self.size[rx] += self.size[ry]
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        return rx

    def connected(self, x: str, y: str) -> bool:
        return self.find(x) == self.find(y)

    def cluster_members(self, x: str) -> list[str]:
        root = self.find(x)
        return [k for k in self.parent if self.find(k) == root]

    def clusters(self) -> dict[str, list[str]]:
        result = defaultdict(list)
        for k in self.parent:
            result[self.find(k)].append(k)
        return dict(result)


# ---------------------------------------------------------------------------
# Bayesian Correlation Scorer
# ---------------------------------------------------------------------------
class BayesianScorer:
    """Incremental Bayesian posterior for pairwise identity correlation."""

    def __init__(self):
        self.log_odds: dict[tuple[str, str], float] = {}
        self.evidence_count: dict[tuple[str, str], int] = defaultdict(int)
        self.last_update: dict[tuple[str, str], float] = {}

        # Prior log-odds (start skeptical)
        self.prior_log_odds = -2.0  # ~0.12 prior probability

        # Evidence weights (log-likelihood ratios)
        self.LR_TIMING = 1.5       # Temporal co-occurrence
        self.LR_RSSI = 1.2         # RSSI correlation
        self.LR_VENDOR = 2.0       # Same vendor OUI
        self.LR_NAME_SIM = 2.5     # Name string similarity
        self.LR_CROSS_PROTO = 3.0  # Cross-protocol same-device indicators
        self.LR_JACCARD = 1.8      # Jaccard similarity of leaked value sets
        self.LR_FORCED = 10.0      # Manual force-link

        # Decay parameters
        self.DECAY_RATE = 0.001    # Log-odds decay per second
        self.LINK_THRESHOLD = 1.5  # Log-odds threshold for correlation link

    def _key(self, a: str, b: str) -> tuple[str, str]:
        return (min(a, b), max(a, b))

    def get_posterior(self, a: str, b: str) -> float:
        """Get current posterior probability for pair."""
        k = self._key(a, b)
        lo = self.log_odds.get(k, self.prior_log_odds)

        # Apply temporal decay
        if k in self.last_update:
            dt = time.time() - self.last_update[k]
            lo -= self.DECAY_RATE * dt

        # Convert log-odds to probability
        return 1.0 / (1.0 + math.exp(-lo))

    def update(self, a: str, b: str, evidence_type: str, strength: float = 1.0):
        """Incremental Bayesian update with evidence."""
        k = self._key(a, b)

        # Initialize if needed
        if k not in self.log_odds:
            self.log_odds[k] = self.prior_log_odds

        # Apply decay first
        if k in self.last_update:
            dt = time.time() - self.last_update[k]
            self.log_odds[k] -= self.DECAY_RATE * dt

        # Apply evidence (multiply likelihood ratio → add to log-odds)
        lr_map = {
            "timing": self.LR_TIMING,
            "rssi": self.LR_RSSI,
            "vendor": self.LR_VENDOR,
            "name_similarity": self.LR_NAME_SIM,
            "cross_protocol": self.LR_CROSS_PROTO,
            "jaccard": self.LR_JACCARD,
            "forced": self.LR_FORCED,
        }
        base_lr = lr_map.get(evidence_type, 1.0)
        self.log_odds[k] += base_lr * strength

        # Clamp to prevent extreme certainty
        self.log_odds[k] = max(-10.0, min(self.log_odds[k], 10.0))

        self.evidence_count[k] += 1
        self.last_update[k] = time.time()

    def is_linked(self, a: str, b: str) -> bool:
        k = self._key(a, b)
        return self.log_odds.get(k, self.prior_log_odds) >= self.LINK_THRESHOLD

    def force_link(self, a: str, b: str):
        self.update(a, b, "forced", strength=1.0)


# ---------------------------------------------------------------------------
# Correlation Engine
# ---------------------------------------------------------------------------
class CorrelationEngine:
    def __init__(self, leak_store: LeakStore):
        self.store = leak_store
        self.scorer = BayesianScorer()
        self.uf = UnionFind()
        self._last_process_idx = 0
        self._device_leak_sets: dict[str, set[str]] = defaultdict(set)
        self._device_timestamps: dict[str, list[float]] = defaultdict(list)
        self._device_rssi: dict[str, list[int]] = defaultdict(list)
        self._correlation_edges: dict[str, GraphEdge] = {}

    def cluster_count(self) -> int:
        return len(self.uf.clusters())

    def correlation_count(self) -> int:
        return len(self._correlation_edges)

    def force_link(self, node_a: str, node_b: str):
        """Creator Mode: manually force a correlation."""
        if node_a and node_b and node_a != node_b:
            self.scorer.force_link(node_a, node_b)
            self._create_correlation_edge(node_a, node_b, 0.99)
            self.uf.union(node_a, node_b)
            self._update_cluster_assignments()
            logger.info(f"[CORR] Force-linked {node_a} ↔ {node_b}")

    def process_new_events(self):
        """Process events added since last call — called from graph tick."""
        events = list(self.store.events)
        new_events = events[self._last_process_idx:]
        self._last_process_idx = len(events)

        if not new_events:
            return

        for event in new_events:
            dev_id = f"dev_{event.source_addr}"
            val_id = f"val_{__import__('hashlib').md5(event.leak_value.encode()).hexdigest()[:10]}"

            # Track device feature sets
            self._device_leak_sets[dev_id].add(event.leak_value)
            self._device_timestamps[dev_id].append(event.timestamp)
            self._device_rssi[dev_id].append(event.rssi)

        # Run pairwise correlation on device nodes
        device_ids = [nid for nid, n in self.store.nodes.items()
                      if n.node_type == "device"]

        # Only compare recent pairs to keep it O(n) amortized
        recent_devices = [d for d in device_ids
                          if self.store.nodes[d].last_seen > time.time() - 60]

        for i, dev_a in enumerate(recent_devices):
            for dev_b in recent_devices[i + 1:]:
                if self.uf.connected(dev_a, dev_b):
                    continue  # Already clustered

                self._compute_pairwise_evidence(dev_a, dev_b)

                if self.scorer.is_linked(dev_a, dev_b):
                    confidence = self.scorer.get_posterior(dev_a, dev_b)
                    self._create_correlation_edge(dev_a, dev_b, confidence)
                    self.uf.union(dev_a, dev_b)

        self._update_cluster_assignments()

    def _compute_pairwise_evidence(self, dev_a: str, dev_b: str):
        """Compute all evidence types for a pair of devices."""
        node_a = self.store.nodes.get(dev_a)
        node_b = self.store.nodes.get(dev_b)
        if not node_a or not node_b:
            return

        # 1. Temporal co-occurrence
        ts_a = self._device_timestamps.get(dev_a, [])
        ts_b = self._device_timestamps.get(dev_b, [])
        if ts_a and ts_b:
            min_dt = min(abs(ta - tb) for ta in ts_a[-10:] for tb in ts_b[-10:])
            if min_dt < 2.0:  # Within 2 seconds
                strength = 1.0 - (min_dt / 2.0)
                self.scorer.update(dev_a, dev_b, "timing", strength)

        # 2. RSSI Pearson correlation (if enough samples)
        rssi_a = self._device_rssi.get(dev_a, [])
        rssi_b = self._device_rssi.get(dev_b, [])
        if len(rssi_a) >= 3 and len(rssi_b) >= 3:
            corr = self._pearson(rssi_a[-10:], rssi_b[-10:])
            if corr is not None and corr > 0.6:
                self.scorer.update(dev_a, dev_b, "rssi", corr - 0.6)

        # 3. Vendor match
        if node_a.label[:8] == node_b.label[:8] and node_a.protocol != node_b.protocol:
            self.scorer.update(dev_a, dev_b, "vendor", 0.5)

        # 4. Cross-protocol indicator
        if node_a.protocol != node_b.protocol:
            # Different protocol = stronger evidence if other signals align
            sets_a = self._device_leak_sets.get(dev_a, set())
            sets_b = self._device_leak_sets.get(dev_b, set())
            # Check for overlapping leaked strings (e.g., same device name)
            overlap = sets_a & sets_b
            if overlap:
                self.scorer.update(dev_a, dev_b, "cross_protocol", len(overlap) * 0.5)

        # 5. Jaccard similarity of leaked value sets
        sets_a = self._device_leak_sets.get(dev_a, set())
        sets_b = self._device_leak_sets.get(dev_b, set())
        if sets_a and sets_b:
            jaccard = len(sets_a & sets_b) / len(sets_a | sets_b)
            if jaccard > 0.2:
                self.scorer.update(dev_a, dev_b, "jaccard", jaccard)

        # 6. Name/string similarity (fuzzy matching)
        if node_a.label and node_b.label:
            sim = self._string_similarity(node_a.label, node_b.label)
            if sim > 0.5:
                self.scorer.update(dev_a, dev_b, "name_similarity", sim)

    def _create_correlation_edge(self, dev_a: str, dev_b: str, confidence: float):
        """Create a visual correlation edge."""
        edge_id = f"corr_{min(dev_a, dev_b)}|{max(dev_a, dev_b)}"
        if edge_id not in self._correlation_edges:
            # Blend colors of the two protocols
            na = self.store.nodes.get(dev_a)
            nb = self.store.nodes.get(dev_b)
            color = "#ffffff"  # Correlation edges are white
            if confidence > 0.8:
                color = "#ff00ff"  # High confidence = magenta

            edge = GraphEdge(
                source=dev_a,
                target=dev_b,
                weight=confidence,
                edge_type="correlation",
                color=color,
                animated=True,
            )
            self._correlation_edges[edge_id] = edge
            self.store.edges[edge_id] = edge

            logger.info(
                f"[CORR] New correlation: {dev_a} ↔ {dev_b} "
                f"(confidence: {confidence:.2%})"
            )

            # Add a log entry
            self.store.log_lines.append({
                "ts": time.time(),
                "text": f"[CORR  ] ⚡ LINK: {dev_a[-8:]} ↔ {dev_b[-8:]} ({confidence:.0%})",
                "color": "#ff00ff",
                "rssi": 0,
            })

    def _update_cluster_assignments(self):
        """Update cluster_id on all nodes based on Union-Find."""
        clusters = self.uf.clusters()
        for root, members in clusters.items():
            if len(members) < 2:
                continue
            for member in members:
                if member in self.store.nodes:
                    self.store.nodes[member].cluster_id = root
                    # Boost confidence based on cluster size
                    self.store.nodes[member].confidence = min(
                        0.5 + 0.1 * len(members), 1.0
                    )

    @staticmethod
    def _pearson(x: list[int], y: list[int]) -> Optional[float]:
        """Compute Pearson correlation coefficient."""
        n = min(len(x), len(y))
        if n < 2:
            return None
        x, y = x[:n], y[:n]
        mx = sum(x) / n
        my = sum(y) / n
        sx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / n)
        sy = math.sqrt(sum((yi - my) ** 2 for yi in y) / n)
        if sx == 0 or sy == 0:
            return None
        cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
        return cov / (sx * sy)

    @staticmethod
    def _string_similarity(a: str, b: str) -> float:
        """Simple bigram similarity (Dice coefficient)."""
        if not a or not b:
            return 0.0
        a, b = a.lower(), b.lower()
        if a == b:
            return 1.0
        bigrams_a = {a[i:i + 2] for i in range(len(a) - 1)}
        bigrams_b = {b[i:i + 2] for i in range(len(b) - 1)}
        if not bigrams_a or not bigrams_b:
            return 0.0
        return 2.0 * len(bigrams_a & bigrams_b) / (len(bigrams_a) + len(bigrams_b))


# Bring in math for the module
import math
