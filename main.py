import argparse
import asyncio
import os
import sys
import time
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from config import load_config, save_config, load_contacts
from ble_manager import BLEManager, BLEPeer
from ui import TerminalUI

async def main():
    parser = argparse.ArgumentParser(description="Terminal Talk - Bluetooth P2P Mesh Chat")
    parser.add_argument("--name", "-n", type=str, help="Set your chat nickname")
    parser.add_argument("--share", "-s", action="store_true", help="Show share download link/command")
    args = parser.parse_args()

    config = load_config()
    if args.name:
        config["nickname"] = args.name
        save_config(config)

    nickname = config["nickname"]
    device_id = config["device_id"]

    ui = TerminalUI(nickname)

    # Callback when incoming Bluetooth message / mesh packet is received
    def on_message_received(packet: dict):
        sender = packet.get("source_name", "Unknown")
        text = packet.get("text", "")
        ts = packet.get("timestamp", time.strftime("%H:%M:%S"))
        target_name = packet.get("target_name", "ALL")
        visited = packet.get("visited", [])
        hops = len(visited) if visited else 1
        
        ui.add_message(sender, text, ts, is_self=False, target_name=target_name, hops=hops)
        ui.render_snapshot()

    # Callback when Bluetooth peer list updates
    def on_peers_changed(peers: list):
        ui.update_peers(peers)
        ui.render_snapshot()

    ble = BLEManager(
        nickname=nickname,
        device_id=device_id,
        on_message=on_message_received,
        on_peers_changed=on_peers_changed
    )

    loop = asyncio.get_running_loop()
    ble.start(loop)

    if args.share:
        from share import print_share_info
        print_share_info()
        return

    # Add welcome message
    ui.add_message("System", "Welcome to Terminal Talk! Mesh Routing & Direct Messaging Active.", time.strftime("%H:%M:%S"))
    ui.render_snapshot()

    session = PromptSession()

    with patch_stdout():
        while True:
            try:
                user_input = await session.prompt_async(f"{nickname} [{ui.active_target_name}] > ")
                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    cmd_parts = user_input.split(maxsplit=2)
                    cmd = cmd_parts[0].lower()

                    if cmd in ["/quit", "/exit"]:
                        ui.update_status("Exiting...")
                        break
                    elif cmd in ["/group", "/all"]:
                        ui.set_channel("BROADCAST", "Group Chat")
                        ui.add_message("System", "Switched channel to Group Chat", time.strftime("%H:%M:%S"))
                    elif cmd == "/chat" and len(cmd_parts) > 1:
                        target_name = cmd_parts[1]
                        contacts = load_contacts()
                        target_id = None
                        for dev_id, info in contacts.items():
                            if info.get("nickname").lower() == target_name.lower():
                                target_id = dev_id
                                break
                        if not target_id:
                            target_id = target_name # fallback
                        ui.set_channel(target_id, target_name)
                        ui.add_message("System", f"Switched DM channel to '{target_name}'", time.strftime("%H:%M:%S"))
                    elif cmd == "/msg" and len(cmd_parts) > 2:
                        target_name = cmd_parts[1]
                        msg_text = cmd_parts[2]
                        contacts = load_contacts()
                        target_id = target_name
                        for dev_id, info in contacts.items():
                            if info.get("nickname").lower() == target_name.lower():
                                target_id = dev_id
                                break
                        
                        ts = time.strftime("%H:%M:%S")
                        ui.add_message(nickname, msg_text, ts, is_self=True, target_name=target_name, hops=1)
                        ui.update_status(f"Relaying DM to {target_name}...")
                        ui.render_snapshot()

                        await ble.send_message(msg_text, target_id=target_id, target_name=target_name)
                        ui.update_status(f"Message sent to mesh for {target_name}")

                    elif cmd == "/nick" and len(cmd_parts) > 1:
                        new_nick = cmd_parts[1]
                        nickname = new_nick
                        config["nickname"] = new_nick
                        save_config(config)
                        ble.nickname = new_nick
                        ui.nickname = new_nick
                        ui.add_message("System", f"Nickname changed to '{new_nick}'", time.strftime("%H:%M:%S"))
                    elif cmd == "/contacts":
                        contacts = load_contacts()
                        info_lines = [f"{c['nickname']} (ID: {c['device_id']}, Last: {c['last_seen']})" for c in contacts.values()]
                        summary = ", ".join(info_lines) if info_lines else "No saved contacts yet."
                        ui.add_message("System", f"Saved Contacts: {summary}", time.strftime("%H:%M:%S"))
                    elif cmd == "/peers":
                        peer_names = [f"{p.name} ({p.device_id} {p.rssi}dBm)" for p in ble.peers.values()]
                        info = ", ".join(peer_names) if peer_names else "No direct peers found in range."
                        ui.add_message("System", f"Direct Peers: {info}", time.strftime("%H:%M:%S"))
                    elif cmd == "/share":
                        from share import print_share_info
                        print_share_info()
                    elif cmd == "/help":
                        ui.add_message("System", "Commands: /group, /chat <user>, /msg <user> <text>, /contacts, /nick <name>, /quit", time.strftime("%H:%M:%S"))
                    elif cmd == "/clear":
                        ui.messages.clear()
                    else:
                        ui.add_message("System", f"Unknown command: {cmd}", time.strftime("%H:%M:%S"))
                else:
                    # Broadcast or DM depending on active channel
                    ts = time.strftime("%H:%M:%S")
                    target_id = ui.active_channel
                    target_name = ui.active_target_name

                    ui.add_message(nickname, user_input, ts, is_self=True, target_name=target_name, hops=1)
                    ui.update_status(f"Sending message via Bluetooth Mesh [{target_name}]...")
                    ui.render_snapshot()

                    sent = await ble.send_message(user_input, target_id=target_id, target_name=target_name)
                    if sent:
                        ui.update_status("Message delivered to direct BLE peers!")
                    else:
                        ui.update_status("Relaying message over Mesh (Scanning for relays...)")

                ui.render_snapshot()

            except (KeyboardInterrupt, EOFError):
                break

    ble.stop()
    print("\nGoodbye from Terminal Talk!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
