"""
LEAKPHANTOM v2.3.1 — Setup Wizard
Hardware auto-detection and one-click protocol initialization.
"""

import asyncio
import glob
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from utils import logger


class SetupWizard:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.detected_hardware = {}
        self.thread_key: Optional[str] = None
        self.legal_accepted = False

    async def detect_hardware(self) -> dict:
        """Auto-detect all available capture hardware."""
        logger.info("[WIZARD] Starting hardware detection ...")
        results = {
            "wifi": await self._detect_wifi(),
            "bluetooth": await self._detect_bluetooth(),
            "serial": await self._detect_serial(),
            "tools": self._detect_tools(),
            "platform": platform.system(),
            "demo_available": True,
        }
        self.detected_hardware = results
        logger.info(f"[WIZARD] Detection complete: {results}")
        return results

    async def _detect_wifi(self) -> dict:
        """Detect WiFi adapters capable of monitor mode."""
        adapters = []
        monitor_capable = []

        if platform.system() == "Linux":
            # Check iwconfig
            try:
                result = await _run_cmd("iwconfig 2>/dev/null")
                for line in result.split("\n"):
                    match = re.match(r"^(\w+)\s+IEEE", line)
                    if match:
                        iface = match.group(1)
                        adapters.append(iface)
                        # Check if monitor mode is supported
                        iw_result = await _run_cmd(f"iw phy phy0 info 2>/dev/null | grep monitor")
                        if "monitor" in iw_result.lower():
                            monitor_capable.append(iface)
            except Exception as e:
                logger.debug(f"WiFi detect error: {e}")

            # Also check for airmon-ng
            if shutil.which("airmon-ng"):
                try:
                    result = await _run_cmd("airmon-ng 2>/dev/null")
                    for line in result.split("\n"):
                        if any(chip in line.lower() for chip in ["ath9k", "rt2800", "rtl88", "mt76"]):
                            parts = line.split()
                            if parts:
                                monitor_capable.append(parts[1] if len(parts) > 1 else parts[0])
                except Exception:
                    pass

        elif platform.system() == "Darwin":
            # macOS — limited monitor mode via airport
            try:
                result = await _run_cmd("networksetup -listallhardwareports 2>/dev/null")
                if "Wi-Fi" in result:
                    adapters.append("en0")
                    # macOS can sniff via airport in some configs
                    if os.path.exists("/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"):
                        monitor_capable.append("en0 (limited)")
            except Exception:
                pass

        return {
            "adapters": adapters,
            "monitor_capable": monitor_capable,
            "available": len(monitor_capable) > 0,
        }

    async def _detect_bluetooth(self) -> dict:
        """Detect Bluetooth adapters."""
        adapters = []

        if platform.system() == "Linux":
            try:
                result = await _run_cmd("hciconfig 2>/dev/null")
                for line in result.split("\n"):
                    match = re.match(r"^(hci\d+)", line)
                    if match:
                        adapters.append(match.group(1))
            except Exception:
                pass

            # Also check bluetoothctl
            if not adapters and shutil.which("bluetoothctl"):
                try:
                    result = await _run_cmd("bluetoothctl list 2>/dev/null")
                    if "Controller" in result:
                        adapters.append("hci0")
                except Exception:
                    pass

        elif platform.system() == "Darwin":
            # macOS always has Bluetooth (usually)
            try:
                result = await _run_cmd("system_profiler SPBluetoothDataType 2>/dev/null")
                if "Bluetooth" in result:
                    adapters.append("default")
            except Exception:
                pass

        return {
            "adapters": adapters,
            "available": len(adapters) > 0,
        }

    async def _detect_serial(self) -> dict:
        """Detect serial ports for Zigbee/Thread/Z-Wave dongles."""
        ports = []

        if platform.system() == "Linux":
            for pattern in ["/dev/ttyUSB*", "/dev/ttyACM*"]:
                ports.extend(glob.glob(pattern))
        elif platform.system() == "Darwin":
            for pattern in ["/dev/tty.usbmodem*", "/dev/tty.usbserial*", "/dev/cu.usbmodem*"]:
                ports.extend(glob.glob(pattern))

        # Try to identify device type
        identified = []
        for port in ports:
            info = {"port": port, "type": "unknown"}
            try:
                # Check udevadm for device info (Linux)
                if platform.system() == "Linux":
                    result = await _run_cmd(f"udevadm info -q property {port} 2>/dev/null")
                    if "Silicon_Labs" in result or "CP210" in result:
                        info["type"] = "zigbee_or_thread"
                    elif "Texas_Instruments" in result or "CC2538" in result:
                        info["type"] = "thread"
                    elif "0658:0200" in result:
                        info["type"] = "zwave"
                    elif "nRF" in result.lower() or "nordic" in result.lower():
                        info["type"] = "thread_ble"
            except Exception:
                pass
            identified.append(info)

        return {
            "ports": identified,
            "available": len(ports) > 0,
        }

    def _detect_tools(self) -> dict:
        """Check for required command-line tools."""
        tools = {}
        for tool in ["airmon-ng", "tshark", "hcitool", "hcidump", "spinel-cli.py", "python3"]:
            tools[tool] = shutil.which(tool) is not None
        # Also check Python packages
        for pkg in ["scapy", "pyserial", "bleak"]:
            try:
                __import__(pkg)
                tools[f"py_{pkg}"] = True
            except ImportError:
                tools[f"py_{pkg}"] = False
        return tools

    async def set_thread_key(self, key: str, auto_extract: bool = False) -> dict:
        """Set Thread network master key, optionally auto-extracting from local OTBR."""
        if auto_extract:
            extracted = await self._extract_otbr_key()
            if extracted:
                self.thread_key = extracted
                return {"status": "ok", "key": extracted[:8] + "..." , "source": "otbr"}
            return {"status": "error", "message": "Could not auto-extract from OTBR"}

        # Validate hex key (Thread keys are 16 bytes = 32 hex chars)
        clean = key.replace(":", "").replace(" ", "").strip()
        if len(clean) == 32 and all(c in "0123456789abcdefABCDEF" for c in clean):
            self.thread_key = clean
            return {"status": "ok", "key": clean[:8] + "..."}
        return {"status": "error", "message": "Invalid key format (expected 32 hex chars)"}

    async def _extract_otbr_key(self) -> Optional[str]:
        """Try to extract Thread network key from OpenThread Border Router."""
        # Method 1: ot-ctl
        try:
            result = await _run_cmd("sudo ot-ctl networkkey 2>/dev/null")
            clean = result.strip().replace(" ", "")
            if len(clean) == 32:
                return clean
        except Exception:
            pass

        # Method 2: REST API (OTBR web interface)
        try:
            result = await _run_cmd(
                "curl -s http://localhost:8081/node/dataset/active 2>/dev/null"
            )
            import json
            data = json.loads(result)
            if "NetworkKey" in data:
                return data["NetworkKey"].replace(":", "")
        except Exception:
            pass

        return None

    async def initialize_all(self, config: dict = None) -> dict:
        """One-click initialization of all detected protocols."""
        config = config or {}
        results = {}

        if not self.detected_hardware:
            await self.detect_hardware()

        hw = self.detected_hardware

        # WiFi
        if hw.get("wifi", {}).get("available"):
            results["wifi"] = await self.orchestrator.init_wifi(
                hw["wifi"]["monitor_capable"][0] if hw["wifi"]["monitor_capable"] else None
            )
        else:
            results["wifi"] = {"status": "unavailable", "fallback": "demo"}

        # Bluetooth
        if hw.get("bluetooth", {}).get("available"):
            results["bluetooth"] = await self.orchestrator.init_bluetooth(
                hw["bluetooth"]["adapters"][0] if hw["bluetooth"]["adapters"] else None
            )
        else:
            results["bluetooth"] = {"status": "unavailable", "fallback": "demo"}

        # Serial devices (Zigbee/Thread/Z-Wave)
        serial_ports = hw.get("serial", {}).get("ports", [])
        for port_info in serial_ports:
            port = port_info["port"]
            ptype = port_info["type"]
            if ptype in ("zigbee_or_thread", "thread", "thread_ble"):
                results["thread"] = await self.orchestrator.init_thread(
                    port, self.thread_key
                )
            elif ptype == "zwave":
                results["zwave"] = await self.orchestrator.init_zwave(port)
            else:
                results[f"serial_{port}"] = await self.orchestrator.init_generic_serial(port)

        # If nothing real is available, enable demo mode
        all_unavailable = all(
            v.get("status") == "unavailable" or v.get("fallback") == "demo"
            for v in results.values()
        ) if results else True

        if all_unavailable:
            results["demo"] = {"status": "active", "message": "No hardware detected, using realistic demo mode"}
            self.orchestrator.demo_mode = True

        return {"protocols": results, "demo_mode": self.orchestrator.demo_mode}


async def _run_cmd(cmd: str, timeout: float = 10.0) -> str:
    """Run a shell command asynchronously with timeout."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        return ""
    except Exception:
        return ""
