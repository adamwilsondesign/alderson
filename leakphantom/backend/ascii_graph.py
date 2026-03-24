"""
LEAKPHANTOM v2.3.1 — ASCII Force-Directed Graph Engine
Grid-snapped Fruchterman-Reingold with particles, pulses, and snap animations.
Runs server-side, streams positions to frontend for rendering.
"""

import math
import random
import time
from typing import Optional

from utils import GraphNode, Particle, PROTOCOL_COLORS, logger
from correlation_engine import CorrelationEngine


class ASCIIGraphEngine:
    """Server-side force-directed layout with particle system."""

    # Layout constants
    GRID_W = 160           # Character grid width
    GRID_H = 50            # Character grid height
    REPULSION = 500.0      # Coulomb repulsion constant
    ATTRACTION = 0.01      # Hooke spring constant
    DAMPING = 0.85         # Velocity damping
    SNAP_GRID = 2          # Snap positions to 2-char grid
    MAX_VELOCITY = 5.0     # Max velocity per tick
    IDEAL_EDGE_LEN = 12.0  # Ideal edge length in grid units
    CENTER_GRAVITY = 0.02  # Pull toward center
    CLUSTER_ATTRACTION = 0.005  # Extra pull for cluster members

    # Particle system
    MAX_PARTICLES = 80
    PARTICLE_SPEED = 0.025

    def __init__(self, correlation_engine: CorrelationEngine):
        self.corr = correlation_engine
        self.store = correlation_engine.store
        self.particles: list[Particle] = []
        self._hover_id: Optional[str] = None
        self._tick = 0
        self._snap_animations: dict[str, dict] = {}  # node_id → {target_x, target_y, progress}
        self._flash_edges: dict[str, float] = {}  # edge_id → flash_start_time

    def set_hover(self, node_id: Optional[str]):
        self._hover_id = node_id

    def step(self):
        """One physics tick — call at ~20fps."""
        self._tick += 1

        # Process new correlation events
        self.corr.process_new_events()

        nodes = self.store.nodes
        edges = self.store.edges

        if not nodes:
            return

        # Initialize new node positions randomly
        for nid, node in nodes.items():
            if node.x == 0 and node.y == 0:
                node.x = random.uniform(10, self.GRID_W - 10)
                node.y = random.uniform(5, self.GRID_H - 5)
                node.vx = random.uniform(-1, 1)
                node.vy = random.uniform(-1, 1)

        # --- Fruchterman-Reingold forces ---
        forces: dict[str, tuple[float, float]] = {nid: (0.0, 0.0) for nid in nodes}
        node_list = list(nodes.items())

        # Repulsion (all pairs)
        for i, (id_a, na) in enumerate(node_list):
            for id_b, nb in node_list[i + 1:]:
                dx = na.x - nb.x
                dy = na.y - nb.y
                dist = math.sqrt(dx * dx + dy * dy) + 0.01
                # Coulomb repulsion
                force = self.REPULSION / (dist * dist)
                fx = (dx / dist) * force
                fy = (dy / dist) * force
                forces[id_a] = (forces[id_a][0] + fx, forces[id_a][1] + fy)
                forces[id_b] = (forces[id_b][0] - fx, forces[id_b][1] - fy)

        # Attraction (edges)
        for eid, edge in edges.items():
            na = nodes.get(edge.source)
            nb = nodes.get(edge.target)
            if not na or not nb:
                continue
            dx = na.x - nb.x
            dy = na.y - nb.y
            dist = math.sqrt(dx * dx + dy * dy) + 0.01
            # Hooke's law with ideal length
            displacement = dist - self.IDEAL_EDGE_LEN
            force = self.ATTRACTION * displacement
            # Stronger attraction for correlation edges
            if edge.edge_type == "correlation":
                force *= 3.0
            fx = (dx / dist) * force
            fy = (dy / dist) * force
            forces[edge.source] = (forces[edge.source][0] - fx, forces[edge.source][1] - fy)
            forces[edge.target] = (forces[edge.target][0] + fx, forces[edge.target][1] + fy)

        # Cluster centroid attraction
        clusters = self.corr.uf.clusters()
        for root, members in clusters.items():
            if len(members) < 2:
                continue
            # Compute centroid
            cx = sum(nodes[m].x for m in members if m in nodes) / len(members)
            cy = sum(nodes[m].y for m in members if m in nodes) / len(members)
            for m in members:
                if m in nodes and m in forces:
                    dx = cx - nodes[m].x
                    dy = cy - nodes[m].y
                    forces[m] = (
                        forces[m][0] + dx * self.CLUSTER_ATTRACTION,
                        forces[m][1] + dy * self.CLUSTER_ATTRACTION,
                    )

        # Center gravity
        cx, cy = self.GRID_W / 2, self.GRID_H / 2
        for nid, node in nodes.items():
            dx = cx - node.x
            dy = cy - node.y
            forces[nid] = (
                forces[nid][0] + dx * self.CENTER_GRAVITY,
                forces[nid][1] + dy * self.CENTER_GRAVITY,
            )

        # Apply forces
        for nid, node in nodes.items():
            if node.pinned:
                continue
            if nid in self._snap_animations:
                # Node is in snap animation — interpolate toward target
                anim = self._snap_animations[nid]
                anim["progress"] = min(anim["progress"] + 0.05, 1.0)
                t = _ease_out_cubic(anim["progress"])
                node.x = node.x + (anim["tx"] - node.x) * t * 0.1
                node.y = node.y + (anim["ty"] - node.y) * t * 0.1
                if anim["progress"] >= 1.0:
                    del self._snap_animations[nid]
                continue

            fx, fy = forces.get(nid, (0, 0))
            node.vx = (node.vx + fx) * self.DAMPING
            node.vy = (node.vy + fy) * self.DAMPING

            # Clamp velocity
            speed = math.sqrt(node.vx ** 2 + node.vy ** 2)
            if speed > self.MAX_VELOCITY:
                node.vx = (node.vx / speed) * self.MAX_VELOCITY
                node.vy = (node.vy / speed) * self.MAX_VELOCITY

            node.x += node.vx
            node.y += node.vy

            # Boundary clamping
            node.x = max(2, min(node.x, self.GRID_W - 2))
            node.y = max(2, min(node.y, self.GRID_H - 2))

            # Grid snapping (soft — every few ticks)
            if self._tick % 5 == 0:
                node.x = round(node.x / self.SNAP_GRID) * self.SNAP_GRID
                node.y = round(node.y / self.SNAP_GRID) * self.SNAP_GRID

        # --- Update confidence pulses ---
        for nid, node in nodes.items():
            age = time.time() - node.last_seen
            # Pulse intensity: brighter when recent
            pulse = max(0.2, 1.0 - age / 30.0)
            # Overlay cluster confidence
            if node.cluster_id:
                pulse = min(pulse + node.confidence * 0.3, 1.0)
            node.size = max(1, min(int(pulse * 5) + 1, 8))

        # --- Particle system ---
        self._update_particles()

        # --- Flash cleanup ---
        now = time.time()
        expired = [eid for eid, t in self._flash_edges.items() if now - t > 0.5]
        for eid in expired:
            del self._flash_edges[eid]

    def _update_particles(self):
        """Move existing particles and spawn new ones."""
        edges = self.store.edges
        nodes = self.store.nodes

        # Advance existing particles
        alive = []
        for p in self.particles:
            p.progress += p.speed
            if p.progress < 1.0:
                alive.append(p)
            # else: particle reached destination (absorbed)
        self.particles = alive

        # Spawn new particles on active edges
        if len(self.particles) < self.MAX_PARTICLES and edges:
            # Weighted toward recent edges
            edge_list = list(edges.values())
            for _ in range(min(3, self.MAX_PARTICLES - len(self.particles))):
                edge = random.choice(edge_list)
                src = nodes.get(edge.source)
                tgt = nodes.get(edge.target)
                if not src or not tgt:
                    continue

                # Use leaked values as particle labels
                recent_events = [
                    e for e in list(self.store.events)[-50:]
                    if f"dev_{e.source_addr}" == edge.source
                ]
                label = ""
                if recent_events:
                    label = recent_events[-1].leak_value[:12]

                p = Particle(
                    edge_source=edge.source,
                    edge_target=edge.target,
                    progress=0.0,
                    speed=self.PARTICLE_SPEED + random.uniform(-0.005, 0.01),
                    label=label,
                    color=edge.color,
                )
                self.particles.append(p)

    def trigger_snap_animation(self, node_id: str, target_x: float, target_y: float):
        """Trigger a 600ms snap animation for a node (e.g., on new correlation)."""
        self._snap_animations[node_id] = {
            "tx": target_x,
            "ty": target_y,
            "progress": 0.0,
        }

    def trigger_edge_flash(self, edge_id: str):
        """Trigger a white flash on a new edge."""
        self._flash_edges[edge_id] = time.time()

    # ------------------------------------------------------------------
    # Serialization for WebSocket frames
    # ------------------------------------------------------------------
    def get_nodes(self) -> list[dict]:
        result = []
        for nid, node in self.store.nodes.items():
            d = node.to_dict()
            d["hover"] = (nid == self._hover_id)
            d["pulse_phase"] = (self._tick * 0.1 + hash(nid) % 100) % (2 * math.pi)
            d["in_snap"] = nid in self._snap_animations
            result.append(d)
        return result

    def get_edges(self) -> list[dict]:
        result = []
        for eid, edge in self.store.edges.items():
            d = edge.to_dict()
            d["flash"] = eid in self._flash_edges
            if d["flash"]:
                d["flash_progress"] = min(
                    (time.time() - self._flash_edges[eid]) / 0.5, 1.0
                )
            result.append(d)
        return result

    def get_particles(self) -> list[dict]:
        nodes = self.store.nodes
        result = []
        for p in self.particles:
            src = nodes.get(p.edge_source)
            tgt = nodes.get(p.edge_target)
            if not src or not tgt:
                continue
            # Interpolate position along edge
            x = src.x + (tgt.x - src.x) * p.progress
            y = src.y + (tgt.y - src.y) * p.progress
            d = p.to_dict()
            d["x"] = round(x, 1)
            d["y"] = round(y, 1)
            result.append(d)
        return result


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3
