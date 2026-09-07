import argparse
import asyncio
import os
import sys
import time
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from config import load_config, save_config, load_contacts, panic_wipe_data, prompt_nickname_if_needed
from ble_manager import BLEManager, BLEPeer
from ui import TerminalUI

async def main():
    parser = argparse.ArgumentParser(description="Bluetooth Talk - P2P Bluetooth Mesh Terminal Chat")
    parser.add_argument("--name", "-n", type=str, help="Set your chat nickname")
    parser.add_argument("--channel", "-c", type=str, default="#general", help="Join default channel")
    parser.add_argument("--share", "-s", action="store_true", help="Show share download link/command")
    args = parser.parse_args()

    # Load configuration & prompt for nickname if first time
    config = load_config()
    if args.name:
        config["nickname"] = args.name
        config["custom_nickname_set"] = True
        save_config(config)
    else:
        # Prompt interactively if custom nickname has not been set yet
        config = prompt_nickname_if_needed(config)

    nickname = config["nickname"]
    device_id = config["device_id"]

    ui = TerminalUI(nickname)
    ui.set_channel(args.channel, args.channel)

    # Callback when incoming Bluetooth message / mesh packet is received
    def on_message_received(packet: dict):
        sender = packet.get("source_name", "Unknown")
        text = packet.get("text", "")
        ts = packet.get("timestamp", time.strftime("%H:%M:%S"))
        target_name = packet.get("target_name", "ALL")
        channel = packet.get("channel", "#general")
        visited = packet.get("visited", [])
        hops = len(visited) if visited else 1
        
        ui.add_message(sender, text, ts, is_self=False, channel=channel, target_name=target_name, hops=hops)
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

    # Welcome message
    ui.add_message("Bluetooth Talk", f"Welcome <{nickname}>! Joined channel {args.channel}.", time.strftime("%H:%M:%S"), channel=args.channel)
    ui.render_snapshot()

    session = PromptSession()

    with patch_stdout():
        while True:
            try:
                user_input = await session.prompt_async(f"<{nickname}> [{ui.active_target_name}] > ")
                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.startswith("/"):
                    cmd_parts = user_input.split(maxsplit=2)
                    cmd = cmd_parts[0].lower()

                    if cmd in ["/quit", "/exit"]:
                        ui.update_status("Exiting...")
                        break
                    elif cmd in ["/join", "/channel"] and len(cmd_parts) > 1:
                        target_chan = cmd_parts[1]
                        if not target_chan.startswith("#"):
                            target_chan = f"#{target_chan}"
                        ui.set_channel(target_chan, target_chan)
                        ui.add_message("Bluetooth Talk", f"Joined channel {target_chan}", time.strftime("%H:%M:%S"), channel=target_chan)
                    
                    elif cmd == "/chat" and len(cmd_parts) > 1:
                        target_arg = cmd_parts[1]
                        target_name = target_arg
                        target_id = target_arg

                        # Handle numbered peer index shortcut e.g. /chat 1
                        if target_arg.isdigit():
                            idx = int(target_arg) - 1
                            if 0 <= idx < len(ui.peers):
                                peer = ui.peers[idx]
                                target_name = peer.name
                                target_id = peer.device_id

                        ui.set_channel(target_id, target_name)
                        ui.add_message("Bluetooth Talk", f"Switched DM channel to '{target_name}'", time.strftime("%H:%M:%S"), channel="DM", target_name=target_name)

                    elif cmd == "/msg" and len(cmd_parts) > 2:
                        target_arg = cmd_parts[1]
                        msg_text = cmd_parts[2]
                        target_name = target_arg
                        target_id = target_arg

                        if target_arg.isdigit():
                            idx = int(target_arg) - 1
                            if 0 <= idx < len(ui.peers):
                                peer = ui.peers[idx]
                                target_name = peer.name
                                target_id = peer.device_id

                        ts = time.strftime("%H:%M:%S")
                        ui.add_message(nickname, msg_text, ts, is_self=True, channel="DM", target_name=target_name, hops=1)
                        ui.update_status(f"Sending Direct Message to {target_name}...")
                        ui.render_snapshot()

                        await ble.send_message(msg_text, target_id=target_id, target_name=target_name, channel="DM")
                        ui.update_status(f"DM dispatched to mesh for {target_name}")

                    elif cmd == "/panic":
                        panic_wipe_data()
                        ui.messages.clear()
                        ui.peers.clear()
                        ui.add_message("Bluetooth Talk", "⚠️ PANIC MODE: All local logs and contacts wiped!", time.strftime("%H:%M:%S"))
                        ui.update_status("Panic Mode Triggered: Data Wiped")

                    elif cmd == "/nick" and len(cmd_parts) > 1:
                        new_nick = cmd_parts[1]
                        nickname = new_nick
                        config["nickname"] = new_nick
                        config["custom_nickname_set"] = True
                        save_config(config)
                        ble.nickname = new_nick
                        ui.nickname = new_nick
                        ui.add_message("Bluetooth Talk", f"Nickname changed to <{new_nick}>", time.strftime("%H:%M:%S"))
                    
                    elif cmd in ["/who", "/peers"]:
                        peer_info = [f"<{p.name}> ({p.peer_type} {p.rssi}dBm)" for p in ble.peers.values()]
                        summary = ", ".join(peer_info) if peer_info else "No active peers in direct range."
                        ui.add_message("Bluetooth Talk", f"Active Mesh Peers: {summary}", time.strftime("%H:%M:%S"))
                    
                    elif cmd == "/contacts":
                        contacts = load_contacts()
                        info_lines = [f"<{c['nickname']}> (ID: {c['device_id']})" for c in contacts.values()]
                        summary = ", ".join(info_lines) if info_lines else "No contacts history."
                        ui.add_message("Bluetooth Talk", f"Saved Contacts: {summary}", time.strftime("%H:%M:%S"))
                    
                    elif cmd == "/share":
                        from share import print_share_info
                        print_share_info()
                    
                    elif cmd == "/help":
                        ui.add_message("Bluetooth Talk", "Shortcuts: /chat <#>, /join <#chan>, /msg <user> <text>, /who, /panic, /nick <name>, /quit", time.strftime("%H:%M:%S"))
                    
                    elif cmd == "/clear":
                        ui.messages.clear()
                    
                    else:
                        ui.add_message("Bluetooth Talk", f"Unknown command: {cmd}", time.strftime("%H:%M:%S"))
                else:
                    # Send message to active channel or DM
                    ts = time.strftime("%H:%M:%S")
                    target_chan = ui.active_target_name

                    if target_chan.startswith("#"):
                        target_id = "BROADCAST"
                        target_name = "ALL"
                        chan_tag = target_chan
                    else:
                        target_id = ui.active_channel
                        target_name = ui.active_target_name
                        chan_tag = "DM"

                    ui.add_message(nickname, user_input, ts, is_self=True, channel=chan_tag, target_name=target_name, hops=1)
                    ui.update_status(f"Sending message to {target_chan}...")
                    ui.render_snapshot()

                    sent = await ble.send_message(user_input, target_id=target_id, target_name=target_name, channel=chan_tag)
                    if sent:
                        ui.update_status(f"Message sent to {target_chan}!")
                    else:
                        ui.update_status("Dispatched over Mesh")

                ui.render_snapshot()

            except (KeyboardInterrupt, EOFError):
                break

    ble.stop()
    print("\nGoodbye from Bluetooth Talk!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
