# LEAKPHANTOM v2.3.1

**Multi-Protocol Identity Leakage Capturer with Cyberpunk Terminal UI**

```
██╗     ███████╗ █████╗ ██╗  ██╗██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗
██║     ██╔════╝██╔══██╗██║ ██╔╝██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║
██║     █████╗  ███████║█████╔╝ ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║
██║     ██╔══╝  ██╔══██║██╔═██╗ ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║
███████╗███████╗██║  ██║██║  ██╗██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║
╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝
```

## LEGAL DISCLAIMER

**This tool is intended for authorized security research, penetration testing, and educational purposes ONLY.**

Unauthorized monitoring of network traffic may violate local, state, and federal laws including:
- The Wiretap Act (18 U.S.C. § 2511)
- Computer Fraud and Abuse Act (18 U.S.C. § 1030)
- GDPR, CCPA, and other privacy regulations

**Always obtain proper written authorization before use. The developers assume no liability for misuse.**

---

## First Run in 30 Seconds

```bash
# 1. Setup (installs Python deps in a venv)
./setup.sh

# 2. Run
./run.sh

# 3. Open browser
open http://127.0.0.1:8666
```

The Setup Wizard auto-detects hardware on first run. If no capture hardware is found, LEAKPHANTOM runs in **Demo Mode** with realistic simulated traffic across all 6 protocols.

---

## Supported Protocols

| Protocol | Hardware Required | Capture Method |
|---|---|---|
| **WiFi Probes** | Monitor-mode WiFi adapter (Atheros, Realtek, MediaTek) | airmon-ng + tshark / Scapy |
| **BLE Advertising** | Any Bluetooth adapter | bleak (Python) |
| **Zigbee / 802.15.4** | CC2531 USB dongle or similar | pyserial + Scapy |
| **Thread** | nRF52840 dongle / OpenThread NCP | Pyspinel + tshark |
| **Matter** | mDNS on local network | tshark / zeroconf |
| **Z-Wave** | Sigma Designs UZB / Aeotec Z-Stick | pyserial |

## Recommended Hardware

- **WiFi**: Alfa AWUS036ACH (Realtek RTL8812AU) — dual-band monitor mode
- **BLE**: Built-in Bluetooth or CSR 4.0 USB dongle
- **Thread/Zigbee**: Nordic nRF52840 Dongle (PCA10059) — $10, supports both
- **Z-Wave**: Aeotec Z-Stick Gen5+ — serial sniffer mode

---

## Architecture

```
leakphantom/
├── backend/
│   ├── main.py                 # FastAPI + WebSocket server
│   ├── wizard.py               # Setup wizard (hardware detection)
│   ├── orchestrator.py         # Protocol subprocess manager + demo mode
│   ├── correlation_engine.py   # Bayesian scoring + Union-Find + Louvain
│   ├── ascii_graph.py          # Force-directed layout + particle system
│   ├── sound_engine.py         # Web Audio synthesis definitions
│   ├── parser.py               # Protocol-specific frame parsers
│   ├── utils.py                # Data models, LeakStore, lookups
│   ├── oui_database.json       # MAC vendor lookup
│   └── ble_services.json       # BLE UUID → service name
├── frontend/
│   ├── index.html              # Terminal UI shell
│   ├── style.css               # CRT effects, ANSI colors, animations
│   ├── script.js               # Graph renderer, audio, Easter eggs
│   └── vite.config.js          # Dev server config
├── setup.sh                    # One-command setup
├── run.sh                      # One-command run
├── requirements.txt            # Python dependencies
├── package.json                # Frontend (optional Vite dev)
└── README.md
```

## Correlation Engine

The engine uses **Bayesian posterior updates** for probabilistic identity correlation:

- **Temporal co-occurrence**: Devices seen within 2s of each other
- **RSSI Pearson correlation**: Signal strength patterns over time
- **Vendor OUI matching**: Same manufacturer across protocols
- **Jaccard set similarity**: Overlapping leaked value sets
- **String similarity**: Dice coefficient on device names
- **Cross-protocol linking**: Same identifiers across WiFi/BLE/Thread

Linked identities are clustered using **Union-Find** with path compression and union-by-rank.

## Visualization

- **Force-directed graph**: Fruchterman-Reingold with grid snapping
- **Flowing particles**: Travel along Bresenham paths carrying leaked strings
- **Pulsing nodes**: Intensity tied to cluster confidence
- **Snap animations**: 600ms ease-out-cubic when correlations form
- **Matrix rain**: Uses real captured data, intensifies on correlation bursts
- **CRT effects**: Scanlines, vignette, subtle glitch keyframes

## Sound Design

All audio is synthesized client-side via Web Audio API:

- Ambient low-frequency hum with LFO wobble
- Heartbeat synced to leak rate
- Protocol-specific blip tones (WiFi=440Hz, BLE=587Hz, etc.)
- Correlation lock-in arpeggios
- Particle whoosh noise bursts
- Spatial panning based on graph X position

## Easter Eggs

- **Konami Code** (↑↑↓↓←→←→BA): Color invert + "Hello, friend..."
- **Type "fsociety"**: Matrix burst + "THEY OWN YOU"
- **666 leaks**: Hidden "E" flash + sub-bass hit
- **Creator Mode** (Ctrl+Shift+C): Manual correlation forcing

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LEAKPHANTOM_HOST` | `127.0.0.1` | Bind address |
| `LEAKPHANTOM_PORT` | `8666` | Server port |

## Thread Network Key

For Thread/802.15.4 decryption, provide the network master key via the Setup Wizard:
- Manually enter the 32-character hex key
- Or auto-extract from a local OpenThread Border Router (OTBR)

---

## Development

For frontend hot-reload during development:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` and `/ws` to the Python backend on port 8666.

---

*LEAKPHANTOM v2.3.1 — Phantom Protocol*
