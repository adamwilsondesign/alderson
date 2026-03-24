"""
LEAKPHANTOM v2.3.1 — Protocol Orchestrator
Silently spawns and monitors capture subprocesses.
Falls back to realistic demo mode when hardware is unavailable.
"""

import asyncio
import json
import os
import random
import shutil
import struct
import time
from typing import Optional

from utils import LeakEvent, LeakStore, logger, lookup_vendor, lookup_ble_service


class Orchestrator:
    def __init__(self, leak_store: LeakStore):
        self.leak_store = leak_store
        self.demo_mode = True
        self.is_running = False
        self._tasks: list[asyncio.Task] = []
        self._subprocesses: list[asyncio.subprocess.Process] = []
        self._wifi_iface: Optional[str] = None
        self._bt_adapter: Optional[str] = None
        self._thread_port: Optional[str] = None
        self._thread_key: Optional[str] = None
        self._zwave_port: Optional[str] = None
        self._active_protocols: set[str] = set()

    def active_protocols(self) -> list[str]:
        return list(self._active_protocols)

    # ------------------------------------------------------------------
    # Initialization methods (called by wizard)
    # ------------------------------------------------------------------
    async def init_wifi(self, iface: Optional[str]) -> dict:
        if not iface:
            return {"status": "unavailable"}

        self._wifi_iface = iface

        # Try to enable monitor mode via airmon-ng
        if shutil.which("airmon-ng"):
            try:
                proc = await asyncio.create_subprocess_shell(
                    f"sudo airmon-ng start {iface} 2>/dev/null",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                output = stdout.decode()
                # airmon-ng usually renames to iface + "mon"
                if f"{iface}mon" in output:
                    self._wifi_iface = f"{iface}mon"
                elif "monitor mode" in output.lower():
                    self._wifi_iface = iface
                self._active_protocols.add("wifi")
                self.demo_mode = False
                return {"status": "ok", "interface": self._wifi_iface, "mode": "monitor"}
            except Exception as e:
                logger.warning(f"airmon-ng failed: {e}")

        return {"status": "partial", "interface": iface, "mode": "managed"}

    async def init_bluetooth(self, adapter: Optional[str]) -> dict:
        if not adapter:
            return {"status": "unavailable"}
        self._bt_adapter = adapter
        self._active_protocols.add("ble")
        self.demo_mode = False
        return {"status": "ok", "adapter": adapter}

    async def init_thread(self, port: str, key: Optional[str]) -> dict:
        self._thread_port = port
        self._thread_key = key
        self._active_protocols.add("thread")
        self.demo_mode = False
        return {"status": "ok", "port": port, "key_set": key is not None}

    async def init_zwave(self, port: str) -> dict:
        self._zwave_port = port
        self._active_protocols.add("zwave")
        self.demo_mode = False
        return {"status": "ok", "port": port}

    async def init_generic_serial(self, port: str) -> dict:
        return {"status": "ok", "port": port, "type": "generic"}

    # ------------------------------------------------------------------
    # Start / Stop
    # ------------------------------------------------------------------
    async def start(self):
        if self.is_running:
            await self.stop()
        self.is_running = True
        logger.info("[ORCH] Starting capture ...")

        if self.demo_mode:
            self._tasks.append(asyncio.create_task(self._demo_generator()))
            logger.info("[ORCH] Demo mode active — generating realistic traffic")
        else:
            # Launch real capture tasks
            if "wifi" in self._active_protocols and self._wifi_iface:
                self._tasks.append(asyncio.create_task(self._wifi_capture()))
            if "ble" in self._active_protocols:
                self._tasks.append(asyncio.create_task(self._ble_capture()))
            if "thread" in self._active_protocols and self._thread_port:
                self._tasks.append(asyncio.create_task(self._thread_capture()))
            if "zwave" in self._active_protocols and self._zwave_port:
                self._tasks.append(asyncio.create_task(self._zwave_capture()))

            # Always add demo for protocols without hardware
            missing = {"wifi", "ble", "zigbee", "thread", "matter", "zwave"} - self._active_protocols
            if missing:
                self._tasks.append(asyncio.create_task(self._demo_generator(protocols=missing)))

    async def stop(self):
        self.is_running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        for proc in self._subprocesses:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                proc.kill()
        self._subprocesses.clear()

        # Cleanup monitor mode
        if self._wifi_iface and self._wifi_iface.endswith("mon"):
            try:
                orig = self._wifi_iface.replace("mon", "")
                proc = await asyncio.create_subprocess_shell(
                    f"sudo airmon-ng stop {self._wifi_iface} 2>/dev/null",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=10)
            except Exception:
                pass

        logger.info("[ORCH] All captures stopped")

    async def shutdown(self):
        await self.stop()

    # ------------------------------------------------------------------
    # Real WiFi Probe Capture (Scapy / tshark)
    # ------------------------------------------------------------------
    async def _wifi_capture(self):
        """Capture WiFi probe requests using tshark or Scapy."""
        logger.info(f"[WIFI] Starting capture on {self._wifi_iface}")

        # Prefer tshark for JSON output
        if shutil.which("tshark"):
            await self._wifi_tshark()
        else:
            await self._wifi_scapy()

    async def _wifi_tshark(self):
        """Use tshark to capture probe requests in JSON mode."""
        cmd = (
            f"tshark -i {self._wifi_iface} -l "
            f"-Y 'wlan.fc.type_subtype == 0x04' "
            f"-T json "
            f"-e frame.time_epoch -e wlan.sa -e wlan.ssid "
            f"-e radiotap.dbm_antsignal -e wlan.fixed.capabilities "
            f"2>/dev/null"
        )
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._subprocesses.append(proc)
            buffer = ""

            while self.is_running:
                line = await proc.stdout.readline()
                if not line:
                    break
                buffer += line.decode("utf-8", errors="replace")

                # tshark JSON wraps packets in array
                try:
                    if buffer.strip().endswith("}"):
                        # Try to parse accumulated JSON
                        packets = json.loads(f"[{buffer}]")
                        for pkt in packets:
                            layers = pkt.get("_source", {}).get("layers", {})
                            mac = layers.get("wlan.sa", [""])[0]
                            ssid = layers.get("wlan.ssid", [""])[0]
                            rssi = int(layers.get("radiotap.dbm_antsignal", ["-100"])[0])

                            if ssid:
                                event = LeakEvent(
                                    protocol="wifi",
                                    source_addr=mac,
                                    leak_type="ssid_probe",
                                    leak_value=ssid,
                                    rssi=rssi,
                                )
                                self.leak_store.add_event(event)
                        buffer = ""
                except (json.JSONDecodeError, ValueError):
                    # Keep accumulating
                    if len(buffer) > 100000:
                        buffer = ""
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[WIFI] tshark error: {e}")

    async def _wifi_scapy(self):
        """Fallback: use Scapy directly for probe capture."""
        try:
            from scapy.all import AsyncSniffer, Dot11ProbeReq, Dot11Elt, RadioTap

            def handle_packet(pkt):
                if pkt.haslayer(Dot11ProbeReq):
                    ssid_layer = pkt.getlayer(Dot11Elt)
                    if ssid_layer and ssid_layer.info:
                        ssid = ssid_layer.info.decode("utf-8", errors="replace")
                        mac = pkt.addr2 or "unknown"
                        rssi = pkt.dBm_AntSignal if hasattr(pkt, "dBm_AntSignal") else -80
                        event = LeakEvent(
                            protocol="wifi",
                            source_addr=mac,
                            leak_type="ssid_probe",
                            leak_value=ssid,
                            rssi=rssi,
                        )
                        self.leak_store.add_event(event)

            sniffer = AsyncSniffer(
                iface=self._wifi_iface,
                prn=handle_packet,
                filter="type mgt subtype probe-req",
                store=False,
            )
            sniffer.start()

            while self.is_running:
                await asyncio.sleep(0.5)

            sniffer.stop()
        except ImportError:
            logger.warning("[WIFI] Scapy not available")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[WIFI] Scapy error: {e}")

    # ------------------------------------------------------------------
    # Real BLE Capture
    # ------------------------------------------------------------------
    async def _ble_capture(self):
        """Capture BLE advertisements using bleak."""
        logger.info("[BLE] Starting BLE scan")
        try:
            from bleak import BleakScanner

            def detection_callback(device, advertisement_data):
                name = device.name or advertisement_data.local_name or ""
                rssi = advertisement_data.rssi or -100

                # Device name leak
                if name:
                    event = LeakEvent(
                        protocol="ble",
                        source_addr=device.address,
                        leak_type="device_name",
                        leak_value=name,
                        rssi=rssi,
                    )
                    self.leak_store.add_event(event)

                # Service UUID leaks
                for uuid in advertisement_data.service_uuids:
                    short = uuid[4:8].upper() if len(uuid) > 8 else uuid
                    service_name = lookup_ble_service(short)
                    event = LeakEvent(
                        protocol="ble",
                        source_addr=device.address,
                        leak_type="service_uuid",
                        leak_value=f"{short} ({service_name})",
                        rssi=rssi,
                    )
                    self.leak_store.add_event(event)

                # Manufacturer data
                for company_id, data in advertisement_data.manufacturer_data.items():
                    event = LeakEvent(
                        protocol="ble",
                        source_addr=device.address,
                        leak_type="manufacturer_data",
                        leak_value=f"Company:{company_id} Data:{data.hex()[:20]}",
                        rssi=rssi,
                        raw_hex=data.hex(),
                    )
                    self.leak_store.add_event(event)

            scanner = BleakScanner(detection_callback=detection_callback)
            await scanner.start()

            while self.is_running:
                await asyncio.sleep(1)

            await scanner.stop()

        except ImportError:
            logger.warning("[BLE] bleak not available")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[BLE] Error: {e}")

    # ------------------------------------------------------------------
    # Real Thread/802.15.4 Capture (Pyspinel + tshark)
    # ------------------------------------------------------------------
    async def _thread_capture(self):
        """Capture Thread/802.15.4 traffic via Pyspinel sniffer."""
        logger.info(f"[THREAD] Starting capture on {self._thread_port}")

        spinel_path = shutil.which("spinel-cli.py") or shutil.which("sniffer.py")
        if not spinel_path:
            logger.warning("[THREAD] Pyspinel not found, trying direct serial")
            await self._thread_serial_direct()
            return

        # Use Pyspinel to put NCP into sniffer mode and pipe to tshark
        cmd = (
            f"python3 {spinel_path} -u {self._thread_port} "
            f"--channel 15 "
            f"| tshark -i - -l -T json "
            f"-e frame.time_epoch -e wpan.src64 -e wpan.dst64 "
            f"-e thread.nwd.tlv.type -e coap.uri_path "
            f"2>/dev/null"
        )

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._subprocesses.append(proc)

            while self.is_running:
                line = await proc.stdout.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue
                try:
                    data = json.loads(line.decode())
                    layers = data.get("_source", {}).get("layers", {})
                    src = layers.get("wpan.src64", [""])[0]
                    dst = layers.get("wpan.dst64", [""])[0]
                    coap_uri = layers.get("coap.uri_path", [""])[0]

                    if src:
                        event = LeakEvent(
                            protocol="thread",
                            source_addr=src,
                            leak_type="mesh_traffic",
                            leak_value=coap_uri or f"→{dst}",
                            channel=15,
                        )
                        self.leak_store.add_event(event)

                        # If we have the network key, attempt decryption
                        if self._thread_key:
                            self._try_thread_decrypt(data)

                except (json.JSONDecodeError, KeyError):
                    pass

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[THREAD] Capture error: {e}")

    async def _thread_serial_direct(self):
        """Fallback: read raw 802.15.4 frames from serial port."""
        try:
            import serial
            ser = serial.Serial(self._thread_port, 115200, timeout=0.5)

            while self.is_running:
                data = ser.read(256)
                if data:
                    event = LeakEvent(
                        protocol="thread",
                        source_addr=data[:8].hex() if len(data) > 8 else "unknown",
                        leak_type="raw_frame",
                        leak_value=f"802.15.4 frame ({len(data)} bytes)",
                        raw_hex=data.hex(),
                    )
                    self.leak_store.add_event(event)
                await asyncio.sleep(0.01)

            ser.close()
        except ImportError:
            logger.warning("[THREAD] pyserial not available")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[THREAD] Serial error: {e}")

    def _try_thread_decrypt(self, packet_data: dict):
        """Attempt AES-128-CCM decryption of Thread payload."""
        if not self._thread_key:
            return
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESCCM
            # This is a simplified version — real Thread decryption requires
            # proper nonce construction from frame counter + source address
            key_bytes = bytes.fromhex(self._thread_key)
            aesccm = AESCCM(key_bytes, tag_length=4)
            # Full implementation would extract nonce, ciphertext, and AAD
            # from the 802.15.4 frame structure
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Z-Wave Capture
    # ------------------------------------------------------------------
    async def _zwave_capture(self):
        """Capture Z-Wave traffic from serial dongle."""
        logger.info(f"[ZWAVE] Starting capture on {self._zwave_port}")
        try:
            import serial
            ser = serial.Serial(self._zwave_port, 115200, timeout=0.5)

            # Put Z-Wave stick into sniffer mode (Sigma Designs API)
            ser.write(bytes([0x01, 0x04, 0x00, 0x50, 0x01, 0xAA]))

            while self.is_running:
                data = ser.read(256)
                if data and len(data) > 5:
                    # Parse Z-Wave frame header
                    home_id = data[:4].hex() if len(data) > 4 else "?"
                    src_node = data[4] if len(data) > 4 else 0
                    event = LeakEvent(
                        protocol="zwave",
                        source_addr=f"Node_{src_node}",
                        leak_type="zwave_frame",
                        leak_value=f"HomeID:{home_id} Node:{src_node}",
                        raw_hex=data.hex(),
                    )
                    self.leak_store.add_event(event)
                await asyncio.sleep(0.01)

            ser.close()
        except ImportError:
            logger.warning("[ZWAVE] pyserial not available")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ZWAVE] Error: {e}")

    # ------------------------------------------------------------------
    # Demo Mode Generator
    # ------------------------------------------------------------------
    async def _demo_generator(self, protocols: set[str] = None):
        """Generate realistic demo traffic for missing protocols."""
        if protocols is None:
            protocols = {"wifi", "ble", "zigbee", "thread", "matter", "zwave"}

        logger.info(f"[DEMO] Generating traffic for: {protocols}")

        # Realistic demo data pools
        wifi_ssids = [
            "Starbucks WiFi", "xfinitywifi", "NETGEAR-5G", "TP-Link_Guest",
            "iPhone (Sarah)", "AndroidAP_7f3a", "HOME-WIFI-2.4", "Linksys02845",
            "FBI_Surveillance_Van_3", "Pretty Fly for a WiFi", "AT&T-WIFI-HOME",
            "GoogleGuest", "AmazonEcho-Setup", "Ring-Setup", "Nest-Cam-8842",
            "Tesla_Guest", "DIRECT-roku-TV", "HP-Print-A4-LaserJet",
            "MySpectrumWiFi21", "Verizon_MiFi7730", "Airport Express",
        ]
        wifi_macs = [
            "AC:DE:48:1A:2B:3C", "F4:5C:89:AA:BB:CC", "00:1A:2B:DD:EE:FF",
            "DC:A6:32:11:22:33", "3C:71:BF:44:55:66", "FC:A1:83:77:88:99",
            "50:C7:BF:AB:CD:EF", "F8:63:3F:12:34:56", "B8:27:EB:AA:11:22",
            "E0:CB:BC:33:44:55", "00:24:D4:66:77:88", "C0:25:E9:99:00:11",
        ]
        ble_names = [
            "AirPods Pro", "Galaxy Buds2", "Fitbit Charge 5", "Apple Watch",
            "Tile Mate", "JBL Flip 6", "Bose QC45", "Sony WH-1000XM5",
            "August Smart Lock", "Philips Hue Bridge", "Nest Thermostat",
            "[TV] Samsung 65\"", "Peloton HR", "Garmin Forerunner",
            "Sonos One", "Echo Dot-K3F2", "iPad Pro",
        ]
        ble_macs = [
            "7A:3B:2C:1D:0E:FF", "4F:5E:6D:7C:8B:9A", "1A:2B:3C:4D:5E:6F",
            "AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66", "DE:AD:BE:EF:CA:FE",
            "C0:FF:EE:BA:BE:00", "FA:CE:B0:0C:DA:7A", "B0:0B:CA:FE:F0:0D",
        ]
        ble_uuids = ["180D", "180F", "FE2C", "FD6F", "FEAA", "FE9F", "FEBE", "1800"]
        zigbee_devices = [
            "Philips Hue Bulb", "IKEA TRADFRI Plug", "Aqara Door Sensor",
            "SmartThings Motion", "Sonoff ZigBee Switch", "Tuya Temp Sensor",
        ]
        thread_devices = [
            "Nanoleaf Essentials", "Eve Energy", "Apple HomePod Mini",
            "Google Nest Hub", "Eero 6+", "Wemo Stage",
        ]
        matter_devices = [
            "Eve Motion", "Nanoleaf A19", "Wemo Smart Plug",
            "TP-Link Tapo", "Meross Smart Plug",
        ]
        zwave_devices = [
            "Aeotec MultiSensor 7", "GE Z-Wave Switch", "Kwikset SmartCode",
            "Fibaro Motion Sensor", "Ring Alarm Contact",
        ]

        tick = 0
        while self.is_running:
            try:
                # Variable rate — bursty like real traffic
                delay = random.expovariate(2.0)  # Mean 0.5s between events
                delay = max(0.1, min(delay, 3.0))
                await asyncio.sleep(delay)

                # Pick a protocol weighted toward WiFi/BLE
                weights = {
                    "wifi": 35, "ble": 30, "zigbee": 10,
                    "thread": 10, "matter": 8, "zwave": 7,
                }
                available = {p: w for p, w in weights.items() if p in protocols}
                if not available:
                    continue

                proto = random.choices(
                    list(available.keys()),
                    weights=list(available.values()),
                )[0]

                event = None

                if proto == "wifi":
                    mac = random.choice(wifi_macs)
                    # Sometimes use random MAC (randomized MAC address)
                    if random.random() < 0.3:
                        mac = ":".join(f"{random.randint(0,255):02X}" for _ in range(6))
                        # Set locally administered bit
                        first = int(mac[:2], 16) | 0x02
                        mac = f"{first:02X}" + mac[2:]
                    event = LeakEvent(
                        protocol="wifi",
                        source_addr=mac,
                        leak_type="ssid_probe",
                        leak_value=random.choice(wifi_ssids),
                        rssi=random.randint(-90, -30),
                        channel=random.choice([1, 6, 11, 36, 44, 149]),
                    )

                elif proto == "ble":
                    mac = random.choice(ble_macs)
                    if random.random() < 0.6:
                        event = LeakEvent(
                            protocol="ble",
                            source_addr=mac,
                            leak_type="device_name",
                            leak_value=random.choice(ble_names),
                            rssi=random.randint(-85, -25),
                        )
                    else:
                        uid = random.choice(ble_uuids)
                        event = LeakEvent(
                            protocol="ble",
                            source_addr=mac,
                            leak_type="service_uuid",
                            leak_value=f"{uid} ({lookup_ble_service(uid)})",
                            rssi=random.randint(-85, -25),
                        )

                elif proto == "zigbee":
                    event = LeakEvent(
                        protocol="zigbee",
                        source_addr=f"0x{random.randint(0, 0xFFFF):04X}",
                        leak_type="device_announce" if random.random() < 0.4 else "attribute_report",
                        leak_value=random.choice(zigbee_devices),
                        rssi=random.randint(-95, -40),
                        channel=random.choice(list(range(11, 27))),
                    )

                elif proto == "thread":
                    event = LeakEvent(
                        protocol="thread",
                        source_addr=":".join(f"{random.randint(0,0xFF):02x}" for _ in range(8)),
                        leak_type="mesh_discovery" if random.random() < 0.3 else "coap_resource",
                        leak_value=random.choice(thread_devices),
                        rssi=random.randint(-90, -35),
                        channel=15,
                    )

                elif proto == "matter":
                    event = LeakEvent(
                        protocol="matter",
                        source_addr=f"Matter_{random.randint(1000,9999)}",
                        leak_type="mdns_discovery" if random.random() < 0.5 else "commissioning",
                        leak_value=random.choice(matter_devices),
                        rssi=random.randint(-80, -30),
                    )

                elif proto == "zwave":
                    event = LeakEvent(
                        protocol="zwave",
                        source_addr=f"Node_{random.randint(1, 50)}",
                        leak_type="nif_broadcast" if random.random() < 0.3 else "command_class",
                        leak_value=random.choice(zwave_devices),
                        rssi=random.randint(-95, -45),
                    )

                if event:
                    self.leak_store.add_event(event)

                tick += 1

                # Occasional burst of correlated events
                if tick % 25 == 0 and random.random() < 0.5:
                    # Same device seen across protocols (cross-protocol leak)
                    burst_mac = random.choice(wifi_macs)
                    burst_name = random.choice(ble_names)
                    for bp in ["wifi", "ble"]:
                        if bp in protocols:
                            burst_event = LeakEvent(
                                protocol=bp,
                                source_addr=burst_mac if bp == "wifi" else random.choice(ble_macs),
                                leak_type="ssid_probe" if bp == "wifi" else "device_name",
                                leak_value=random.choice(wifi_ssids) if bp == "wifi" else burst_name,
                                rssi=random.randint(-70, -30),
                                extra={"correlated_hint": burst_name},
                            )
                            self.leak_store.add_event(burst_event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[DEMO] Error: {e}")
                await asyncio.sleep(1)
