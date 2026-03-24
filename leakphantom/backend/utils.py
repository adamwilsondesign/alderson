"""
LEAKPHANTOM v2.3.1 — Shared utilities, data store, and logging.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("leakphantom")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class LeakEvent:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    protocol: str = ""          # wifi, ble, zigbee, thread, matter, zwave
    source_addr: str = ""       # MAC, short addr, etc.
    leak_type: str = ""         # ssid_probe, device_name, uuid, network_key, etc.
    leak_value: str = ""        # the actual leaked string
    rssi: int = -100
    channel: int = 0
    raw_hex: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class GraphNode:
    id: str
    label: str
    protocol: str
    node_type: str              # device, ssid, service, cluster
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    size: int = 1
    confidence: float = 0.0
    color: str = "#00ff41"
    last_seen: float = field(default_factory=time.time)
    cluster_id: Optional[str] = None
    pinned: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "protocol": self.protocol,
            "type": self.node_type,
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "size": self.size,
            "confidence": round(self.confidence, 3),
            "color": self.color,
            "cluster_id": self.cluster_id,
            "age": round(time.time() - self.last_seen, 1),
        }


@dataclass
class GraphEdge:
    source: str
    target: str
    weight: float = 1.0
    edge_type: str = "leak"     # leak, correlation, cluster
    color: str = "#00ff41"
    animated: bool = True
    created: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "weight": round(self.weight, 3),
            "type": self.edge_type,
            "color": self.color,
            "animated": self.animated,
            "age": round(time.time() - self.created, 1),
        }


@dataclass
class Particle:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    edge_source: str = ""
    edge_target: str = ""
    progress: float = 0.0       # 0..1 along the edge
    speed: float = 0.02
    label: str = ""             # the leaked string fragment
    color: str = "#00ff41"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "src": self.edge_source,
            "tgt": self.edge_target,
            "p": round(self.progress, 3),
            "label": self.label,
            "color": self.color,
        }


# ---------------------------------------------------------------------------
# Protocol color mapping
# ---------------------------------------------------------------------------
PROTOCOL_COLORS = {
    "wifi": "#00ff41",
    "ble": "#00d4ff",
    "zigbee": "#ff6600",
    "thread": "#a855f7",
    "matter": "#f59e0b",
    "zwave": "#ef4444",
    "unknown": "#666666",
}

NODE_TYPE_SHAPES = {
    "device": "●",
    "ssid": "◆",
    "service": "■",
    "cluster": "⬡",
    "gateway": "▲",
}


# ---------------------------------------------------------------------------
# LeakStore — central data repository
# ---------------------------------------------------------------------------
class LeakStore:
    def __init__(self):
        self.events: deque[LeakEvent] = deque(maxlen=50000)
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self.log_lines: deque[dict] = deque(maxlen=500)
        self._stats = defaultdict(int)
        self._start_time = time.time()

    def add_event(self, event: LeakEvent):
        self.events.append(event)
        self._stats["total_leaks"] += 1
        self._stats[f"proto_{event.protocol}"] += 1
        self._stats[f"type_{event.leak_type}"] += 1

        # Add log line
        color = PROTOCOL_COLORS.get(event.protocol, "#00ff41")
        self.log_lines.append({
            "ts": time.time(),
            "text": f"[{event.protocol.upper():6s}] {event.leak_type}: {event.leak_value[:50]}",
            "color": color,
            "rssi": event.rssi,
        })

        # Create or update nodes
        self._ensure_node(event)

    def _ensure_node(self, event: LeakEvent):
        # Device node (by source address)
        dev_id = f"dev_{event.source_addr}"
        if dev_id not in self.nodes:
            self.nodes[dev_id] = GraphNode(
                id=dev_id,
                label=event.source_addr[-8:] if len(event.source_addr) > 8 else event.source_addr,
                protocol=event.protocol,
                node_type="device",
                color=PROTOCOL_COLORS.get(event.protocol, "#00ff41"),
            )
        else:
            self.nodes[dev_id].last_seen = time.time()
            self.nodes[dev_id].size = min(self.nodes[dev_id].size + 1, 10)

        # Leak value node (SSID, device name, UUID, etc.)
        val_id = f"val_{hashlib.md5(event.leak_value.encode()).hexdigest()[:10]}"
        if val_id not in self.nodes:
            self.nodes[val_id] = GraphNode(
                id=val_id,
                label=event.leak_value[:20],
                protocol=event.protocol,
                node_type="ssid" if event.leak_type == "ssid_probe" else "service",
                color=PROTOCOL_COLORS.get(event.protocol, "#00ff41"),
            )
        else:
            self.nodes[val_id].last_seen = time.time()

        # Edge: device → leak value
        edge_id = f"{dev_id}|{val_id}"
        if edge_id not in self.edges:
            self.edges[edge_id] = GraphEdge(
                source=dev_id,
                target=val_id,
                edge_type="leak",
                color=PROTOCOL_COLORS.get(event.protocol, "#00ff41"),
            )
        else:
            self.edges[edge_id].weight = min(self.edges[edge_id].weight + 0.1, 5.0)

    def get_recent_logs(self, n: int = 30) -> list[dict]:
        return list(self.log_lines)[-n:]

    def get_stats(self) -> dict:
        return {
            "total_leaks": self._stats["total_leaks"],
            "unique_devices": sum(1 for n in self.nodes.values() if n.node_type == "device"),
            "unique_values": sum(1 for n in self.nodes.values() if n.node_type != "device"),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "uptime": round(time.time() - self._start_time, 1),
            "proto_wifi": self._stats.get("proto_wifi", 0),
            "proto_ble": self._stats.get("proto_ble", 0),
            "proto_zigbee": self._stats.get("proto_zigbee", 0),
            "proto_thread": self._stats.get("proto_thread", 0),
            "proto_matter": self._stats.get("proto_matter", 0),
            "proto_zwave": self._stats.get("proto_zwave", 0),
        }

    def get_node_detail(self, node_id: str) -> Optional[dict]:
        node = self.nodes.get(node_id)
        if not node:
            return None
        # Gather related edges and events
        related_edges = [e.to_dict() for e in self.edges.values()
                         if e.source == node_id or e.target == node_id]
        related_events = [asdict(ev) for ev in self.events
                          if f"dev_{ev.source_addr}" == node_id
                          or f"val_{hashlib.md5(ev.leak_value.encode()).hexdigest()[:10]}" == node_id][-20:]
        return {
            "node": node.to_dict(),
            "edges": related_edges,
            "events": related_events,
        }

    def export_all(self) -> dict:
        return {
            "version": "2.3.1",
            "exported_at": time.time(),
            "stats": self.get_stats(),
            "events": [asdict(e) for e in self.events],
            "nodes": {k: v.to_dict() for k, v in self.nodes.items()},
            "edges": {k: v.to_dict() for k, v in self.edges.items()},
        }


# ---------------------------------------------------------------------------
# OUI / Vendor lookup (embedded mini-database)
# ---------------------------------------------------------------------------
OUI_DATABASE = {
    "00:1A:2B": "Apple",
    "AC:DE:48": "Apple",
    "F4:5C:89": "Apple",
    "DC:A6:32": "Raspberry Pi",
    "B8:27:EB": "Raspberry Pi",
    "00:1E:C0": "Microchip",
    "3C:71:BF": "Google",
    "F8:0F:F9": "Google",
    "FC:A1:83": "Amazon",
    "68:54:FD": "Amazon",
    "50:C7:BF": "TP-Link",
    "C0:25:E9": "TP-Link",
    "00:24:D4": "Intel",
    "F8:63:3F": "Samsung",
    "00:07:AB": "Samsung",
    "E0:CB:BC": "Samsung",
}


def lookup_vendor(mac: str) -> str:
    prefix = mac[:8].upper()
    return OUI_DATABASE.get(prefix, "Unknown")


# ---------------------------------------------------------------------------
# BLE service UUID lookup
# ---------------------------------------------------------------------------
BLE_SERVICES = {
    "180D": "Heart Rate",
    "180F": "Battery Service",
    "1800": "Generic Access",
    "1801": "Generic Attribute",
    "181C": "User Data",
    "FE2C": "Google Nearby",
    "FD6F": "Exposure Notification",
    "FEAA": "Eddystone",
    "FE9F": "Google",
    "FEF3": "Google",
    "FEBE": "Bose",
}


def lookup_ble_service(uuid_str: str) -> str:
    return BLE_SERVICES.get(uuid_str.upper(), f"Custom ({uuid_str})")
