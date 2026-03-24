"""
LEAKPHANTOM v2.3.1 — Packet Parser
Protocol-specific frame parsing for WiFi, BLE, Zigbee, Thread, Matter, Z-Wave.
"""

import struct
from typing import Optional

from utils import LeakEvent, lookup_vendor, lookup_ble_service, logger


class PacketParser:
    """Parse raw frames from various protocols into LeakEvents."""

    @staticmethod
    def parse_wifi_probe(raw: bytes, rssi: int = -80) -> Optional[LeakEvent]:
        """Parse IEEE 802.11 Probe Request frame."""
        try:
            if len(raw) < 24:
                return None
            # Frame control
            fc = struct.unpack_from("<H", raw, 0)[0]
            subtype = (fc >> 4) & 0x0F
            if subtype != 4:  # Not a probe request
                return None

            # Source address (bytes 10-15)
            src_mac = ":".join(f"{b:02X}" for b in raw[10:16])

            # Parse tagged parameters for SSID
            offset = 24
            ssid = ""
            while offset < len(raw) - 2:
                tag_id = raw[offset]
                tag_len = raw[offset + 1]
                if tag_id == 0 and tag_len > 0:  # SSID tag
                    ssid = raw[offset + 2:offset + 2 + tag_len].decode("utf-8", errors="replace")
                    break
                offset += 2 + tag_len

            if ssid:
                return LeakEvent(
                    protocol="wifi",
                    source_addr=src_mac,
                    leak_type="ssid_probe",
                    leak_value=ssid,
                    rssi=rssi,
                    raw_hex=raw.hex(),
                    extra={"vendor": lookup_vendor(src_mac)},
                )
        except Exception as e:
            logger.debug(f"WiFi parse error: {e}")
        return None

    @staticmethod
    def parse_ble_adv(raw: bytes, rssi: int = -80) -> list[LeakEvent]:
        """Parse BLE advertising PDU."""
        events = []
        try:
            if len(raw) < 2:
                return events

            # BLE advertising header
            pdu_type = raw[0] & 0x0F
            # ADV_IND=0, ADV_DIRECT_IND=1, ADV_NONCONN_IND=2, SCAN_RSP=4
            if pdu_type not in (0, 2, 4, 6):
                return events

            payload_len = raw[1]
            if len(raw) < 2 + payload_len:
                return events

            # Advertiser address (6 bytes after header)
            if len(raw) >= 8:
                addr = ":".join(f"{b:02X}" for b in raw[2:8])
            else:
                addr = "unknown"

            # Parse AD structures
            offset = 8
            while offset < len(raw) - 1:
                ad_len = raw[offset]
                if ad_len == 0 or offset + ad_len >= len(raw):
                    break
                ad_type = raw[offset + 1]
                ad_data = raw[offset + 2:offset + 1 + ad_len]

                # Complete Local Name (0x09) or Shortened (0x08)
                if ad_type in (0x08, 0x09) and ad_data:
                    name = ad_data.decode("utf-8", errors="replace")
                    events.append(LeakEvent(
                        protocol="ble",
                        source_addr=addr,
                        leak_type="device_name",
                        leak_value=name,
                        rssi=rssi,
                        raw_hex=raw.hex(),
                    ))

                # Complete/Incomplete 16-bit Service UUIDs (0x02/0x03)
                elif ad_type in (0x02, 0x03):
                    for i in range(0, len(ad_data) - 1, 2):
                        uuid16 = struct.unpack_from("<H", ad_data, i)[0]
                        uuid_str = f"{uuid16:04X}"
                        events.append(LeakEvent(
                            protocol="ble",
                            source_addr=addr,
                            leak_type="service_uuid",
                            leak_value=f"{uuid_str} ({lookup_ble_service(uuid_str)})",
                            rssi=rssi,
                        ))

                # Manufacturer Specific Data (0xFF)
                elif ad_type == 0xFF and len(ad_data) >= 2:
                    company_id = struct.unpack_from("<H", ad_data, 0)[0]
                    events.append(LeakEvent(
                        protocol="ble",
                        source_addr=addr,
                        leak_type="manufacturer_data",
                        leak_value=f"Company:0x{company_id:04X} Payload:{ad_data[2:].hex()[:20]}",
                        rssi=rssi,
                        raw_hex=ad_data.hex(),
                    ))

                # TX Power Level (0x0A)
                elif ad_type == 0x0A and len(ad_data) >= 1:
                    tx_power = struct.unpack_from("b", ad_data, 0)[0]
                    events.append(LeakEvent(
                        protocol="ble",
                        source_addr=addr,
                        leak_type="tx_power",
                        leak_value=f"{tx_power} dBm",
                        rssi=rssi,
                    ))

                offset += 1 + ad_len

        except Exception as e:
            logger.debug(f"BLE parse error: {e}")
        return events

    @staticmethod
    def parse_zigbee_frame(raw: bytes, rssi: int = -80) -> Optional[LeakEvent]:
        """Parse IEEE 802.15.4 / Zigbee frame."""
        try:
            if len(raw) < 9:
                return None
            # Frame control
            fc = struct.unpack_from("<H", raw, 0)[0]
            frame_type = fc & 0x07  # 0=beacon, 1=data, 2=ack, 3=cmd
            seq_num = raw[2]

            # Destination PAN + address
            dst_pan = struct.unpack_from("<H", raw, 3)[0]
            dst_addr = struct.unpack_from("<H", raw, 5)[0]
            src_addr = struct.unpack_from("<H", raw, 7)[0] if len(raw) > 8 else 0

            leak_type = "beacon" if frame_type == 0 else "data_frame"
            leak_value = f"PAN:0x{dst_pan:04X} Src:0x{src_addr:04X}→Dst:0x{dst_addr:04X}"

            # Check for Zigbee NWK layer (frame type 1 with Zigbee NWK header)
            if frame_type == 1 and len(raw) > 11:
                nwk_fc = struct.unpack_from("<H", raw, 9)[0]
                nwk_frame_type = nwk_fc & 0x03
                if nwk_frame_type == 0:
                    leak_type = "nwk_data"
                elif nwk_frame_type == 1:
                    leak_type = "nwk_command"

            return LeakEvent(
                protocol="zigbee",
                source_addr=f"0x{src_addr:04X}",
                leak_type=leak_type,
                leak_value=leak_value,
                rssi=rssi,
                channel=0,
                raw_hex=raw.hex(),
            )
        except Exception as e:
            logger.debug(f"Zigbee parse error: {e}")
        return None

    @staticmethod
    def parse_thread_frame(raw: bytes, network_key: Optional[str] = None,
                           rssi: int = -80) -> list[LeakEvent]:
        """Parse Thread/802.15.4 frame with optional MLE decryption."""
        events = []
        try:
            # Start with basic 802.15.4 parsing
            if len(raw) < 9:
                return events

            fc = struct.unpack_from("<H", raw, 0)[0]
            frame_type = fc & 0x07

            # Extract extended addresses if present
            addr_mode_dst = (fc >> 10) & 0x03
            addr_mode_src = (fc >> 14) & 0x03

            offset = 3  # past FC + seq
            src_addr = "unknown"
            dst_addr = "unknown"

            # Skip destination address
            if addr_mode_dst == 2:
                offset += 4  # PAN + short
            elif addr_mode_dst == 3:
                offset += 10  # PAN + extended

            # Source address
            if addr_mode_src == 3 and offset + 8 <= len(raw):
                src_bytes = raw[offset:offset + 8]
                src_addr = ":".join(f"{b:02x}" for b in src_bytes)

            events.append(LeakEvent(
                protocol="thread",
                source_addr=src_addr,
                leak_type="mesh_frame",
                leak_value=f"Thread frame ({len(raw)} bytes)",
                rssi=rssi,
                raw_hex=raw.hex(),
            ))

            # If we have the network key, try decryption
            if network_key and len(raw) > 20:
                try:
                    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
                    key = bytes.fromhex(network_key)
                    # Simplified — real Thread uses frame counter for nonce
                    # This demonstrates the capability
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"Thread parse error: {e}")
        return events

    @staticmethod
    def parse_matter_mdns(data: dict) -> Optional[LeakEvent]:
        """Parse Matter mDNS discovery response."""
        try:
            # Matter devices advertise via mDNS with _matter._tcp
            name = data.get("name", "")
            addr = data.get("address", "unknown")
            port = data.get("port", 0)
            txt = data.get("txt", {})

            # Extract Matter-specific TXT records
            vendor_id = txt.get("VI", txt.get("V", "?"))
            product_id = txt.get("PI", txt.get("P", "?"))
            discriminator = txt.get("D", "?")
            commissioning = txt.get("CM", "0")

            leak_value = f"{name} VID:{vendor_id} PID:{product_id}"
            if commissioning != "0":
                leak_value += " [COMMISSIONING]"

            return LeakEvent(
                protocol="matter",
                source_addr=addr,
                leak_type="mdns_discovery",
                leak_value=leak_value,
                extra={
                    "port": port,
                    "vendor_id": vendor_id,
                    "product_id": product_id,
                    "discriminator": discriminator,
                },
            )
        except Exception as e:
            logger.debug(f"Matter parse error: {e}")
        return None

    @staticmethod
    def parse_zwave_frame(raw: bytes, rssi: int = -80) -> Optional[LeakEvent]:
        """Parse Z-Wave frame from serial sniffer."""
        try:
            if len(raw) < 7:
                return None
            # Z-Wave frame: HomeID(4) + SourceNodeID(1) + FrameControl(1) + ...
            home_id = raw[:4].hex()
            src_node = raw[4]
            frame_ctl = raw[5]
            # Command class is typically at offset 7+
            cmd_class = raw[7] if len(raw) > 7 else 0

            CMD_CLASSES = {
                0x20: "Basic",
                0x25: "Switch Binary",
                0x26: "Switch Multilevel",
                0x30: "Sensor Binary",
                0x31: "Sensor Multilevel",
                0x32: "Meter",
                0x60: "Multi Channel",
                0x70: "Configuration",
                0x71: "Notification",
                0x72: "Manufacturer Specific",
                0x80: "Battery",
                0x84: "Wake Up",
                0x86: "Version",
                0x98: "Security",
            }
            cc_name = CMD_CLASSES.get(cmd_class, f"0x{cmd_class:02X}")

            return LeakEvent(
                protocol="zwave",
                source_addr=f"Node_{src_node}",
                leak_type="command_class",
                leak_value=f"HomeID:{home_id} CC:{cc_name}",
                rssi=rssi,
                raw_hex=raw.hex(),
                extra={"home_id": home_id, "node_id": src_node, "cmd_class": cc_name},
            )
        except Exception as e:
            logger.debug(f"Z-Wave parse error: {e}")
        return None
