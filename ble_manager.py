import asyncio
import json
import logging
import platform
import socket
import sys
import time
import uuid
from typing import Callable, Dict, List, Optional, Set
from bleak import BleakScanner, BleakClient
from config import SERVICE_UUID, CHARACTERISTIC_UUID_MSG, update_contact

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("ble_manager")

UDP_PORT = 9999

class BLEPeer:
    def __init__(self, address: str, name: str, device_id: str, rssi: int, peer_type: str = "BLE"):
        self.address = address
        self.name = name
        self.device_id = device_id
        self.rssi = rssi
        self.peer_type = peer_type # "BLE" or "LAN"
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
        self.udp_socket = None

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self.is_scanning = True
        
        # 1. Start BLE Discovery Loop
        asyncio.create_task(self._scan_loop())
        
        # 2. Start Persistent BLE Connection Pool Maintainer (BitChat spec)
        asyncio.create_task(self._connection_pool_loop())
        
        # 3. Start UDP LAN Fallback Loop
        self._start_udp_listener()
        asyncio.create_task(self._udp_heartbeat_loop())
        
        # 4. Start BLE Peripheral (GATT Server) on macOS
        if sys.platform == "darwin":
            self._start_macos_peripheral()

    def _start_udp_listener(self):
        """Sets up UDP Broadcast listener for local network P2P discovery."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", UDP_PORT))
            sock.setblocking(False)
            self.udp_socket = sock
            
            if self._loop:
                self._loop.add_reader(self.udp_socket.fileno(), self._on_udp_data_received)
        except Exception as e:
            logger.debug(f"UDP listener init error: {e}")

    def _on_udp_data_received(self):
        try:
            data, addr = self.udp_socket.recvfrom(4096)
            payload = json.loads(data.decode('utf-8'))
            msg_type = payload.get("type")
            
            if msg_type == "HEARTBEAT":
                dev_id = payload.get("device_id")
                name = payload.get("nickname")
                if dev_id and dev_id != self.device_id:
                    current_time = time.time()
                    updated = False
                    key = f"UDP-{dev_id}"
                    if key not in self.peers:
                        peer = BLEPeer(addr[0], name, dev_id, rssi=0, peer_type="LAN")
                        peer.is_connected = True
                        self.peers[key] = peer
                        updated = True
                    else:
                        peer = self.peers[key]
                        peer.name = name
                        peer.last_seen = current_time
                        peer.is_connected = True
                        updated = True
                    
                    update_contact(dev_id, name, addr[0])
                    if updated and self.on_peers_changed:
                        self.on_peers_changed(list(self.peers.values()))
            
            elif msg_type == "CHAT":
                packet = payload.get("packet", {})
                self.handle_incoming_packet(packet)

        except Exception:
            pass

    async def _udp_heartbeat_loop(self):
        """Periodically broadcasts UDP heartbeat on local network."""
        while self.is_scanning:
            if self.udp_socket:
                try:
                    msg = json.dumps({
                        "type": "HEARTBEAT",
                        "device_id": self.device_id,
                        "nickname": self.nickname
                    }).encode('utf-8')
                    self.udp_socket.sendto(msg, ("<broadcast>", UDP_PORT))
                except Exception:
                    pass
            await asyncio.sleep(2.0)

    def _start_macos_peripheral(self):
        """Starts CoreBluetooth CBPeripheralManager to advertise and receive GATT writes on macOS."""
        try:
            import CoreBluetooth
            from Foundation import NSObject, CBUUID
            
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
                        
                        adv_data = {
                            CoreBluetooth.CBAdvertisementDataLocalNameKey: f"TT:{manager_self.nickname}:{manager_self.device_id}",
                            CoreBluetooth.CBAdvertisementDataServiceUUIDsKey: [service_uuid]
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
        """BitChat Spec: Maintains active GATT connections and subscribes to notifications."""
        while self.is_scanning:
            for addr, peer in list(self.peers.items()):
                if peer.peer_type == "BLE" and not peer.is_connected and not peer.connecting:
                    asyncio.create_task(self._connect_and_subscribe_peer(peer))
            await asyncio.sleep(3.0)

    async def _connect_and_subscribe_peer(self, peer: BLEPeer):
        """Connects BleakClient and subscribes to GATT notifications."""
        peer.connecting = True
        try:
            client = BleakClient(peer.address, timeout=6.0)
            connected = await client.connect()
            if connected:
                peer.client = client
                peer.is_connected = True
                peer.connecting = False

                # Notification Callback
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
            logger.debug(f"Connection pool error for {peer.name}: {e}")
            peer.connecting = False

    async def connect_peer_manual(self, peer_identifier: str) -> bool:
        """Manually trigger connection to a peer by nickname, address, or ID."""
        for addr, peer in list(self.peers.items()):
            if peer_identifier.lower() in [peer.name.lower(), peer.device_id.lower(), peer.address.lower()]:
                if not peer.is_connected:
                    await self._connect_and_subscribe_peer(peer)
                    return peer.is_connected
                return True
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
        """Forwards packet to adjacent peers via BLE and UDP LAN."""
        # 1. Send via UDP LAN Broadcast
        if self.udp_socket:
            try:
                udp_payload = json.dumps({"type": "CHAT", "packet": packet}).encode('utf-8')
                self.udp_socket.sendto(udp_payload, ("<broadcast>", UDP_PORT))
            except Exception:
                pass

        # 2. Send via BLE Active Connections
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
                devices = await BleakScanner.discover(timeout=4.0, return_adv=True)
                current_time = time.time()
                updated = False

                for dev, adv in devices.values():
                    has_service = SERVICE_UUID.lower() in [s.lower() for s in adv.service_uuids]
                    name = adv.local_name or dev.name or ""
                    
                    if has_service or name.startswith("TT:") or name.startswith("TT-"):
                        if name.startswith("TT:"):
                            parts = name.split(":", 2)
                            display_name = parts[1] if len(parts) >= 2 else name
                            dev_id = parts[2] if len(parts) >= 3 else dev.address[:8]
                        elif name.startswith("TT-"):
                            raw = name[3:]
                            if "-" in raw:
                                display_name, dev_id = raw.rsplit("-", 1)
                            else:
                                display_name, dev_id = raw, dev.address[:8]
                        else:
                            display_name = name if name else f"Peer-{dev.address[:6]}"
                            dev_id = dev.address[:8]

                        if dev.address not in self.peers:
                            self.peers[dev.address] = BLEPeer(dev.address, display_name, dev_id, adv.rssi, peer_type="BLE")
                            updated = True
                        else:
                            peer = self.peers[dev.address]
                            peer.rssi = adv.rssi
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
            
            await asyncio.sleep(2.0)

    async def send_message(self, text: str, target_id: str = "BROADCAST", target_name: str = "ALL", channel: str = "#general") -> bool:
        """Sends a mesh packet (0ms instant delivery over active connection pool)."""
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

        # 1. Send via UDP LAN Broadcast
        if self.udp_socket:
            try:
                udp_payload = json.dumps({"type": "CHAT", "packet": packet}).encode('utf-8')
                self.udp_socket.sendto(udp_payload, ("<broadcast>", UDP_PORT))
                success = True
            except Exception as e:
                logger.debug(f"UDP send error: {e}")

        # 2. Send via Active BLE Connection Pool (0-ms instant delivery)
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
        if self.udp_socket:
            try:
                self.udp_socket.close()
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
