import asyncio
import json
import logging
import platform
import socket
import struct
import sys
import time
import uuid
from typing import Callable, Dict, List, Optional, Set
from bleak import BleakScanner, BleakClient
from config import SERVICE_UUID, CHARACTERISTIC_UUID_MSG, update_contact

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("ble_manager")

UDP_PORT = 9999
MCAST_GRP = "239.255.255.250"

class BLEPeer:
    def __init__(self, address: str, name: str, device_id: str, rssi: int, peer_type: str = "BLE"):
        self.address = address
        self.name = name
        self.device_id = device_id
        self.rssi = rssi
        self.peer_type = peer_type # "BLE" or "P2P"
        self.last_seen = time.time()
        self.client: Optional[BleakClient] = None
        self.is_connected = False
        self.connecting = False

class BLEManager:
    def __init__(self, nickname: str, device_id: str, on_message: Callable[[dict], None], on_peers_changed: Callable[[List[BLEPeer]], None]):
        self.nickname = nickname
        self.device_id = device_id
        self.on_message = on_message
        self.on_peers_changed = on_peers_changed
        
        self.peers: Dict[str, BLEPeer] = {}
        self.seen_packets: Set[str] = set()
        self.is_scanning = False
        self.is_advertising = False
        self.peripheral_manager = None
        self._loop = None
        self.udp_listen_sock = None
        self.udp_send_sock = None

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self.is_scanning = True
        
        # 1. Start Multicast + Broadcast UDP Listener
        self._start_udp_sockets()
        asyncio.create_task(self._udp_heartbeat_loop())
        
        # 2. Start BLE Scanning Loop
        asyncio.create_task(self._scan_loop())
        
        # 3. Start BLE Connection Pool Maintainer
        asyncio.create_task(self._connection_pool_loop())
        
        # 4. Start BLE Peripheral (GATT Server) on macOS
        if sys.platform == "darwin":
            self._start_macos_peripheral()

    def _start_udp_sockets(self):
        """Sets up UDP Multicast + Broadcast sockets for instant local discovery."""
        try:
            # Listening Socket (Multicast + Broadcast)
            listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except AttributeError:
                pass
            listen_sock.bind(("", UDP_PORT))
            
            # Join Multicast Group
            mreq = struct.pack("4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
            listen_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            listen_sock.setblocking(False)
            self.udp_listen_sock = listen_sock

            # Sending Socket
            send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            send_sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            self.udp_send_sock = send_sock

            if self._loop:
                self._loop.add_reader(self.udp_listen_sock.fileno(), self._on_udp_data_received)
        except Exception as e:
            logger.debug(f"UDP init error: {e}")

    def _on_udp_data_received(self):
        try:
            data, addr = self.udp_listen_sock.recvfrom(4096)
            payload = json.loads(data.decode('utf-8'))
            msg_type = payload.get("type")
            
            if msg_type == "HEARTBEAT":
                dev_id = payload.get("device_id")
                name = payload.get("nickname")
                if dev_id and dev_id != self.device_id:
                    current_time = time.time()
                    updated = False
                    key = f"P2P-{dev_id}"
                    ble_key = next(
                        (peer_key for peer_key, peer in self.peers.items()
                         if peer.peer_type == "BLE" and
                         (peer.device_id == dev_id or peer.address == addr[0])),
                        None,
                    )
                    if ble_key is not None:
                        peer = self.peers[ble_key]
                        peer.name = name or peer.name
                        peer.last_seen = current_time
                        peer.is_connected = True
                        update_contact(dev_id, peer.name, peer.address)
                        updated = True
                    elif key not in self.peers:
                        peer = BLEPeer(addr[0], name or f"Peer-{dev_id}", dev_id, rssi=0, peer_type="P2P")
                        peer.is_connected = True
                        self.peers[key] = peer
                        updated = True
                    else:
                        peer = self.peers[key]
                        peer.name = name or peer.name
                        peer.address = addr[0]
                        peer.last_seen = current_time
                        peer.is_connected = True
                        updated = True
                    
                    update_contact(dev_id, peer.name, addr[0])
                    if updated and self.on_peers_changed:
                        self.on_peers_changed(list(self.peers.values()))
            
            elif msg_type == "CHAT":
                packet = payload.get("packet", {})
                self.handle_incoming_packet(packet)

        except Exception:
            pass

    async def _udp_heartbeat_loop(self):
        """Broadcasts Multicast and Subnet UDP heartbeats every second."""
        while self.is_scanning:
            if self.udp_send_sock:
                try:
                    msg = json.dumps({
                        "type": "HEARTBEAT",
                        "device_id": self.device_id,
                        "nickname": self.nickname
                    }).encode('utf-8')
                    # Send to Multicast Group
                    self.udp_send_sock.sendto(msg, (MCAST_GRP, UDP_PORT))
                    # Send to Subnet Broadcast
                    self.udp_send_sock.sendto(msg, ("<broadcast>", UDP_PORT))
                except Exception:
                    pass
            await asyncio.sleep(1.5)

    def _start_macos_peripheral(self):
        """Starts CoreBluetooth CBPeripheralManager to advertise GATT Server on macOS."""
        try:
            import CoreBluetooth
            from Foundation import NSObject, CBUUID, NSData
            
            manager_self = self
            
            class PeripheralDelegate(NSObject):
                def peripheralManagerDidUpdateState_(self, peripheral):
                    if peripheral.state() == 5: # CBManagerStatePoweredOn
                        manager_self.is_advertising = True
                        char_uuid = CBUUID.UUIDWithString_(CHARACTERISTIC_UUID_MSG)
                        self.characteristic = CoreBluetooth.CBMutableCharacteristic.alloc().initWithType_properties_value_permissions_(
                            char_uuid,
                            CoreBluetooth.CBCharacteristicPropertyWrite | CoreBluetooth.CBCharacteristicPropertyNotify,
                            None,
                            CoreBluetooth.CBAttributePermissionsWriteable
                        )
                        
                        service_uuid = CBUUID.UUIDWithString_(SERVICE_UUID)
                        self.service = CoreBluetooth.CBMutableService.alloc().initWithType_primary_(service_uuid, True)
                        self.service.setCharacteristics_([self.characteristic])
                        
                        peripheral.addService_(self.service)
                        
                        # Custom manufacturer data for macOS scanner fallback
                        mfg_data = f"TT:{manager_self.nickname}:{manager_self.device_id}".encode('utf-8')
                        ns_mfg_data = NSData.dataWithBytes_length_(mfg_data, len(mfg_data))
                        
                        adv_data = {
                            CoreBluetooth.CBAdvertisementDataLocalNameKey: f"TT:{manager_self.nickname}:{manager_self.device_id}",
                            CoreBluetooth.CBAdvertisementDataServiceUUIDsKey: [service_uuid],
                            CoreBluetooth.CBAdvertisementDataManufacturerDataKey: ns_mfg_data
                        }
                        peripheral.startAdvertising_(adv_data)
                
                def peripheralManager_didReceiveWriteRequests_(self, peripheral, requests):
                    for req in requests:
                        try:
                            data_bytes = bytes(req.value())
                            payload_str = data_bytes.decode('utf-8')
                            payload = json.loads(payload_str)
                            if manager_self._loop and not manager_self._loop.is_closed():
                                manager_self._loop.call_soon_threadsafe(manager_self.handle_incoming_packet, payload)
                        except Exception as e:
                            logger.error(f"Error parsing write request: {e}")
                        peripheral.respondToRequest_withResult_(req, 0)

            self._delegate = PeripheralDelegate.alloc().init()
            self.peripheral_manager = CoreBluetooth.CBPeripheralManager.alloc().initWithDelegate_queue_(self._delegate, None)
        except Exception as e:
            logger.warning(f"Could not start macOS GATT Peripheral: {e}")

    async def _connection_pool_loop(self):
        """Maintains active GATT connections to discovered BLE peers."""
        while self.is_scanning:
            for addr, peer in list(self.peers.items()):
                if peer.peer_type == "BLE" and not peer.is_connected and not peer.connecting:
                    asyncio.create_task(self._connect_and_subscribe_peer(peer))
            await asyncio.sleep(3.0)

    async def _connect_and_subscribe_peer(self, peer: BLEPeer):
        peer.connecting = True
        try:
            client = BleakClient(peer.address, timeout=5.0)
            connected = await client.connect()
            if connected:
                peer.client = client
                peer.is_connected = True
                peer.connecting = False

                def notification_handler(sender, data: bytearray):
                    try:
                        payload = json.loads(data.decode('utf-8'))
                        self.handle_incoming_packet(payload)
                    except Exception:
                        pass

                try:
                    await client.start_notify(CHARACTERISTIC_UUID_MSG, notification_handler)
                except Exception:
                    pass

                if self.on_peers_changed:
                    self.on_peers_changed(list(self.peers.values()))
            else:
                peer.connecting = False
        except Exception as e:
            logger.debug(f"BLE connection error for {peer.name}: {e}")
            peer.connecting = False

    async def connect_peer_manual(self, peer_identifier: str) -> bool:
        """Connect to a discovered BLE peer by name, device ID, or address."""
        identifier = peer_identifier.casefold()
        for peer in self.peers.values():
            if peer.peer_type != "BLE":
                continue
            candidates = (peer.name, peer.device_id, peer.address)
            if any(identifier == str(candidate).casefold() for candidate in candidates):
                if not peer.is_connected:
                    await self._connect_and_subscribe_peer(peer)
                return peer.is_connected
        return False

    async def add_manual_peer(self, ip_or_host: str) -> bool:
        """Allows manual peer addition by IP address or hostname."""
        try:
            dev_id = f"Manual-{ip_or_host[:6]}"
            key = f"P2P-{dev_id}"
            peer = BLEPeer(ip_or_host, f"Peer-{ip_or_host}", dev_id, rssi=0, peer_type="P2P")
            peer.is_connected = True
            self.peers[key] = peer
            
            # Send immediate ping
            msg = json.dumps({
                "type": "HEARTBEAT",
                "device_id": self.device_id,
                "nickname": self.nickname
            }).encode('utf-8')
            self.udp_send_sock.sendto(msg, (ip_or_host, UDP_PORT))
            
            if self.on_peers_changed:
                self.on_peers_changed(list(self.peers.values()))
            return True
        except Exception:
            return False

    def handle_incoming_packet(self, packet: dict):
        """Processes incoming packet, handles BitChat mesh deduplication, local delivery, and multi-hop relaying."""
        packet_id = packet.get("packet_id")
        if not packet_id or packet_id in self.seen_packets:
            return

        self.seen_packets.add(packet_id)
        if len(self.seen_packets) > 2000:
            self.seen_packets = set(list(self.seen_packets)[-1000:])

        source_id = packet.get("source_id", "Unknown")
        source_name = packet.get("source_name", "Unknown")
        target_id = packet.get("target_id", "BROADCAST")
        ttl = packet.get("ttl", 7)
        visited = packet.get("visited", [])

        update_contact(source_id, source_name)

        is_for_me = (target_id == self.device_id)
        is_broadcast = (target_id == "BROADCAST")

        if is_for_me or is_broadcast:
            if self.on_message:
                self.on_message(packet)

        # Multi-Hop Mesh Relay
        if ttl > 1 and self.device_id not in visited and (is_broadcast or not is_for_me):
            relay_packet = packet.copy()
            relay_packet["ttl"] = ttl - 1
            relay_packet["visited"] = visited + [self.device_id]
            asyncio.create_task(self._relay_packet(relay_packet))

    async def _relay_packet(self, packet: dict):
        """Forwards packet to adjacent peers via P2P and BLE."""
        # 1. UDP Multicast & Broadcast
        if self.udp_send_sock:
            try:
                udp_payload = json.dumps({"type": "CHAT", "packet": packet}).encode('utf-8')
                self.udp_send_sock.sendto(udp_payload, (MCAST_GRP, UDP_PORT))
                self.udp_send_sock.sendto(udp_payload, ("<broadcast>", UDP_PORT))
            except Exception:
                pass

        # 2. BLE Connections
        payload_bytes = json.dumps(packet).encode('utf-8')
        for addr, peer in list(self.peers.items()):
            if peer.peer_type == "BLE" and peer.device_id not in packet.get("visited", []):
                try:
                    if peer.client and peer.is_connected:
                        await peer.client.write_gatt_char(CHARACTERISTIC_UUID_MSG, payload_bytes, response=True)
                    else:
                        async with BleakClient(addr, timeout=3.0) as client:
                            if client.is_connected:
                                await client.write_gatt_char(CHARACTERISTIC_UUID_MSG, payload_bytes, response=True)
                except Exception:
                    pass

    async def _scan_loop(self):
        """Continuous BLE scanning task."""
        while self.is_scanning:
            try:
                devices = await BleakScanner.discover(timeout=3.0, return_adv=True)
                current_time = time.time()
                updated = False

                for dev, adv in devices.values():
                    service_uuids = adv.service_uuids or []
                    has_service = SERVICE_UUID.lower() in [s.lower() for s in service_uuids]
                    name = adv.local_name or dev.name or ""
                    mfg_raw = ""
                    for raw_data in (adv.manufacturer_data or {}).values():
                        decoded = bytes(raw_data).decode('utf-8', errors='ignore')
                        if decoded.startswith("TT:"):
                            mfg_raw = decoded
                            break
                    
                    if has_service or name.startswith("TT:") or name.startswith("TT-") or mfg_raw.startswith("TT:"):
                        target_str = mfg_raw if mfg_raw.startswith("TT:") else name
                        if target_str.startswith("TT:"):
                            parts = target_str.split(":", 2)
                            display_name = parts[1] if len(parts) >= 2 else target_str
                            dev_id = parts[2] if len(parts) >= 3 else dev.address[:8]
                        elif target_str.startswith("TT-"):
                            raw = target_str[3:]
                            if "-" in raw:
                                display_name, dev_id = raw.rsplit("-", 1)
                            else:
                                display_name, dev_id = raw, dev.address[:8]
                        else:
                            display_name = target_str if target_str else f"Peer-{dev.address[:6]}"
                            dev_id = dev.address[:8]

                        existing_key = next(
                            (peer_key for peer_key, peer in self.peers.items()
                             if peer.device_id == dev_id),
                            dev.address,
                        )
                        if existing_key not in self.peers:
                            self.peers[dev.address] = BLEPeer(dev.address, display_name, dev_id, adv.rssi, peer_type="BLE")
                            updated = True
                        else:
                            peer = self.peers[existing_key]
                            peer.rssi = adv.rssi
                            if display_name and not display_name.startswith("Peer-"):
                                peer.name = display_name
                            peer.device_id = dev_id
                            peer.last_seen = current_time
                            updated = True
                        
                        update_contact(dev_id, display_name, dev.address)

                # Clean up stale peers (> 30s)
                stale_keys = []
                for addr, peer in self.peers.items():
                    if current_time - peer.last_seen > 30:
                        stale_keys.append(addr)
                        if peer.client:
                            try:
                                asyncio.create_task(peer.client.disconnect())
                            except Exception:
                                pass

                for addr in stale_keys:
                    del self.peers[addr]
                    updated = True

                if updated and self.on_peers_changed:
                    self.on_peers_changed(list(self.peers.values()))

            except Exception as e:
                logger.debug(f"BLE Scan error: {e}")
            
            await asyncio.sleep(1.5)

    async def send_message(self, text: str, target_id: str = "BROADCAST", target_name: str = "ALL", channel: str = "#general") -> bool:
        """Sends a BitChat mesh packet via Multicast/Broadcast and active BLE connections."""
        packet_id = str(uuid.uuid4())[:8]
        packet = {
            "packet_id": packet_id,
            "source_id": self.device_id,
            "source_name": self.nickname,
            "target_id": target_id,
            "target_name": target_name,
            "channel": channel,
            "ttl": 7,
            "visited": [self.device_id],
            "text": text,
            "timestamp": time.strftime("%H:%M:%S")
        }
        self.seen_packets.add(packet_id)

        success = False

        # 1. Send via Multicast & Subnet UDP Broadcast
        if self.udp_send_sock:
            try:
                udp_payload = json.dumps({"type": "CHAT", "packet": packet}).encode('utf-8')
                self.udp_send_sock.sendto(udp_payload, (MCAST_GRP, UDP_PORT))
                self.udp_send_sock.sendto(udp_payload, ("<broadcast>", UDP_PORT))
                
                # Send directly to manual IP peers
                for peer in list(self.peers.values()):
                    if peer.peer_type == "P2P":
                        self.udp_send_sock.sendto(udp_payload, (peer.address, UDP_PORT))

                success = True
            except Exception as e:
                logger.debug(f"UDP send error: {e}")

        # 2. Send via Active BLE Connections
        payload_bytes = json.dumps(packet).encode('utf-8')
        for addr, peer in list(self.peers.items()):
            if peer.peer_type == "BLE":
                try:
                    if peer.client and peer.is_connected:
                        await peer.client.write_gatt_char(CHARACTERISTIC_UUID_MSG, payload_bytes, response=True)
                        success = True
                    else:
                        async with BleakClient(addr, timeout=3.0) as client:
                            if client.is_connected:
                                await client.write_gatt_char(CHARACTERISTIC_UUID_MSG, payload_bytes, response=True)
                                success = True
                except Exception as e:
                    logger.debug(f"BLE send error for {peer.name}: {e}")

        return success

    def stop(self):
        self.is_scanning = False
        if self.udp_listen_sock:
            try:
                self.udp_listen_sock.close()
            except Exception:
                pass
        if self.udp_send_sock:
            try:
                self.udp_send_sock.close()
            except Exception:
                pass
        for peer in self.peers.values():
            if peer.client:
                try:
                    asyncio.create_task(peer.client.disconnect())
                except Exception:
                    pass
        if self.peripheral_manager:
            try:
                self.peripheral_manager.stopAdvertising()
            except Exception:
                pass
