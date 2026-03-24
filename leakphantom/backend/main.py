#!/usr/bin/env python3
"""
LEAKPHANTOM v2.3.1 — Multi-Protocol Identity Leakage Capturer
Main FastAPI application with WebSocket streaming.

LEGAL: This tool is intended for authorized security research,
penetration testing, and educational purposes ONLY. Unauthorized
monitoring of network traffic may violate local, state, and federal
laws. Always obtain proper authorization before use.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from orchestrator import Orchestrator
from correlation_engine import CorrelationEngine
from ascii_graph import ASCIIGraphEngine
from wizard import SetupWizard
from parser import PacketParser
from utils import LeakStore, logger, PROJECT_ROOT

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
orchestrator: Optional[Orchestrator] = None
correlation_engine: Optional[CorrelationEngine] = None
graph_engine: Optional[ASCIIGraphEngine] = None
leak_store: Optional[LeakStore] = None
wizard: Optional[SetupWizard] = None
connected_clients: set[WebSocket] = set()
_broadcast_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator, correlation_engine, graph_engine, leak_store, wizard, _broadcast_task
    logger.info("[LEAKPHANTOM] Booting v2.3.1 ...")

    leak_store = LeakStore()
    correlation_engine = CorrelationEngine(leak_store)
    graph_engine = ASCIIGraphEngine(correlation_engine)
    orchestrator = Orchestrator(leak_store)
    wizard = SetupWizard(orchestrator)

    _broadcast_task = asyncio.create_task(_tick_loop())

    yield

    logger.info("[LEAKPHANTOM] Shutting down ...")
    if _broadcast_task:
        _broadcast_task.cancel()
    if orchestrator:
        await orchestrator.shutdown()


app = FastAPI(title="LEAKPHANTOM", version="2.3.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend
FRONTEND_DIR = PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_assets")


# ---------------------------------------------------------------------------
# Broadcast tick — pushes state to all connected clients
# ---------------------------------------------------------------------------
async def _tick_loop():
    """Main animation / data tick at ~20 fps for smooth graph."""
    tick = 0
    while True:
        try:
            if connected_clients and leak_store:
                # Step physics
                if graph_engine:
                    graph_engine.step()

                frame = _build_frame(tick)
                dead = set()
                for ws in connected_clients:
                    try:
                        await ws.send_text(json.dumps(frame))
                    except Exception:
                        dead.add(ws)
                connected_clients.difference_update(dead)
                tick += 1
            await asyncio.sleep(0.05)  # 20 fps
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Tick error: {e}")
            await asyncio.sleep(0.1)


def _build_frame(tick: int) -> dict:
    """Assemble one frame of data for the frontend."""
    nodes = []
    edges = []
    particles = []
    log_lines = []

    if graph_engine:
        nodes = graph_engine.get_nodes()
        edges = graph_engine.get_edges()
        particles = graph_engine.get_particles()

    if leak_store:
        log_lines = leak_store.get_recent_logs(30)

    stats = {}
    if leak_store:
        stats = leak_store.get_stats()
    if correlation_engine:
        stats["clusters"] = correlation_engine.cluster_count()
        stats["correlations"] = correlation_engine.correlation_count()

    return {
        "type": "frame",
        "tick": tick,
        "timestamp": time.time(),
        "nodes": nodes,
        "edges": edges,
        "particles": particles,
        "log": log_lines,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
@app.get("/")
async def serve_index():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse("<h1>LEAKPHANTOM v2.3.1</h1><p>Frontend not built.</p>")


@app.get("/api/status")
async def get_status():
    return {
        "version": "2.3.1",
        "running": orchestrator.is_running if orchestrator else False,
        "demo_mode": orchestrator.demo_mode if orchestrator else True,
        "stats": leak_store.get_stats() if leak_store else {},
        "protocols": orchestrator.active_protocols() if orchestrator else [],
    }


@app.post("/api/wizard/detect")
async def wizard_detect():
    if wizard:
        return await wizard.detect_hardware()
    return {"error": "Wizard not initialized"}


@app.post("/api/wizard/set-thread-key")
async def wizard_set_thread_key(body: dict):
    key = body.get("key", "")
    auto = body.get("auto_extract", False)
    if wizard:
        return await wizard.set_thread_key(key, auto_extract=auto)
    return {"error": "Wizard not initialized"}


@app.post("/api/wizard/initialize")
async def wizard_initialize(body: dict = None):
    if wizard:
        return await wizard.initialize_all(body or {})
    return {"error": "Wizard not initialized"}


@app.post("/api/wizard/start")
async def wizard_start():
    if orchestrator:
        await orchestrator.start()
        return {"status": "capturing"}
    return {"error": "Orchestrator not initialized"}


@app.post("/api/stop")
async def stop_capture():
    if orchestrator:
        await orchestrator.stop()
        return {"status": "stopped"}
    return {"error": "Orchestrator not initialized"}


@app.post("/api/force-correlate")
async def force_correlate(body: dict):
    """Creator Mode: manually force a correlation between two node IDs."""
    node_a = body.get("node_a")
    node_b = body.get("node_b")
    if correlation_engine and node_a and node_b:
        correlation_engine.force_link(node_a, node_b)
        return {"status": "linked", "a": node_a, "b": node_b}
    return {"error": "Invalid request"}


@app.get("/api/export")
async def export_data():
    if leak_store:
        return leak_store.export_all()
    return {"error": "No data"}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    logger.info(f"[WS] Client connected ({len(connected_clients)} total)")

    # Send initial state
    try:
        await ws.send_text(json.dumps({
            "type": "init",
            "version": "2.3.1",
            "demo_mode": orchestrator.demo_mode if orchestrator else True,
        }))
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            await _handle_ws_message(ws, msg)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        connected_clients.discard(ws)
        logger.info(f"[WS] Client disconnected ({len(connected_clients)} total)")


async def _handle_ws_message(ws: WebSocket, msg: dict):
    """Handle incoming WebSocket commands from frontend."""
    cmd = msg.get("cmd")

    if cmd == "select_node":
        node_id = msg.get("node_id")
        if leak_store:
            detail = leak_store.get_node_detail(node_id)
            await ws.send_text(json.dumps({"type": "node_detail", "data": detail}))

    elif cmd == "hover_node":
        node_id = msg.get("node_id")
        if graph_engine:
            graph_engine.set_hover(node_id)

    elif cmd == "unhover":
        if graph_engine:
            graph_engine.set_hover(None)

    elif cmd == "force_correlate":
        if correlation_engine:
            correlation_engine.force_link(msg.get("a"), msg.get("b"))

    elif cmd == "ping":
        await ws.send_text(json.dumps({"type": "pong", "t": time.time()}))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    print(r"""
    ██╗     ███████╗ █████╗ ██╗  ██╗██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗
    ██║     ██╔════╝██╔══██╗██║ ██╔╝██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║
    ██║     █████╗  ███████║█████╔╝ ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║
    ██║     ██╔══╝  ██╔══██║██╔═██╗ ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║
    ███████╗███████╗██║  ██║██║  ██╗██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║
    ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝
                                         v2.3.1 — PHANTOM PROTOCOL
    """)

    host = os.getenv("LEAKPHANTOM_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("LEAKPHANTOM_PORT", "8666")))

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


if __name__ == "__main__":
    main()
