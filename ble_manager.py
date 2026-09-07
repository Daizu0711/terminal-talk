import asyncio
import json
import logging
import platform
import sys
import time
import uuid
from typing import Callable, Dict, List, Optional, Set
from bleak import BleakScanner, BleakClient
from config import SERVICE_UUID, CHARACTERISTIC_UUID_MSG, update_contact

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("ble_manager")

class BLEPeer:
    def __init__(self, address: str, name: str, device_id: str, rssi: int):
        self.address = address
        self.name = name
        self.device_id = device_id
        self.rssi = rssi
        self.last_seen = time.time()

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

    def start(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self.is_scanning = True
        asyncio.create_task(self._scan_loop())
        
        # Start BLE Peripheral (GATT Server) for receiving incoming messages
        if sys.platform == "darwin":
            self._start_macos_peripheral()
        else:
            logger.info("Non-macOS platform detected: Running BLE Central mode.")

    def _start_macos_peripheral(self):
        """Starts PyObjC CoreBluetooth CBPeripheralManager to advertise and receive messages on macOS."""
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
                            CoreBluetooth.CBAdvertisementDataLocalNameKey: f"TT-{manager_self.nickname}-{manager_self.device_id}",
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

    def handle_incoming_packet(self, packet: dict):
        """Processes incoming packet, handles mesh deduplication, local delivery, and multi-hop relaying."""
        packet_id = packet.get("packet_id")
        if not packet_id or packet_id in self.seen_packets:
            return # Ignore duplicate packet

        # Mark packet as processed
        self.seen_packets.add(packet_id)
        if len(self.seen_packets) > 2000:
            # Clean up old packet IDs
            self.seen_packets = set(list(self.seen_packets)[-1000:])

        source_id = packet.get("source_id", "Unknown")
        source_name = packet.get("source_name", "Unknown")
        target_id = packet.get("target_id", "BROADCAST")
        ttl = packet.get("ttl", 5)
        visited = packet.get("visited", [])

        # Update contact history
        update_contact(source_id, source_name)

        # Check delivery
        is_for_me = (target_id == self.device_id)
        is_broadcast = (target_id == "BROADCAST")

        if is_for_me or is_broadcast:
            # Deliver to local UI
            if self.on_message:
                self.on_message(packet)

        # Multi-Hop Relay Logic
        if ttl > 1 and self.device_id not in visited and (is_broadcast or not is_for_me):
            # Relay to adjacent BLE peers
            relay_packet = packet.copy()
            relay_packet["ttl"] = ttl - 1
            relay_packet["visited"] = visited + [self.device_id]
            asyncio.create_task(self._relay_packet(relay_packet))

    async def _relay_packet(self, packet: dict):
        """Forwards packet to adjacent peers in range."""
        payload_bytes = json.dumps(packet).encode('utf-8')
        for addr, peer in list(self.peers.items()):
            if peer.device_id not in packet.get("visited", []):
                try:
                    async with BleakClient(addr, timeout=4.0) as client:
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
                    
                    if has_service or name.startswith("TT-"):
                        parts = name.split("-")
                        display_name = parts[1] if len(parts) >= 2 else (name or dev.address[:8])
                        dev_id = parts[2] if len(parts) >= 3 else dev.address[:8]

                        if dev.address not in self.peers:
                            self.peers[dev.address] = BLEPeer(dev.address, display_name, dev_id, adv.rssi)
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
                stale_keys = [addr for addr, peer in self.peers.items() if current_time - peer.last_seen > 30]
                for addr in stale_keys:
                    del self.peers[addr]
                    updated = True

                if updated and self.on_peers_changed:
                    self.on_peers_changed(list(self.peers.values()))

            except Exception as e:
                logger.debug(f"BLE Scan error: {e}")
            
            await asyncio.sleep(2.0)

    async def send_message(self, text: str, target_id: str = "BROADCAST", target_name: str = "ALL") -> bool:
        """Sends a mesh packet (Group or DM) to reachable BLE peers."""
        packet_id = str(uuid.uuid4())[:8]
        packet = {
            "packet_id": packet_id,
            "source_id": self.device_id,
            "source_name": self.nickname,
            "target_id": target_id,
            "target_name": target_name,
            "ttl": 5,
            "visited": [self.device_id],
            "text": text,
            "timestamp": time.strftime("%H:%M:%S")
        }
        self.seen_packets.add(packet_id)

        payload_bytes = json.dumps(packet).encode('utf-8')

        if not self.peers:
            return False

        success_count = 0
        for addr, peer in list(self.peers.items()):
            try:
                async with BleakClient(addr, timeout=5.0) as client:
                    if client.is_connected:
                        await client.write_gatt_char(CHARACTERISTIC_UUID_MSG, payload_bytes, response=True)
                        success_count += 1
            except Exception as e:
                logger.debug(f"Failed to send to peer {addr}: {e}")

        return success_count > 0

    def stop(self):
        self.is_scanning = False
        if self.peripheral_manager:
            try:
                self.peripheral_manager.stopAdvertising()
            except Exception:
                pass
