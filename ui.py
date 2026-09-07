import asyncio
import os
import sys
import time
from typing import Dict, List, Optional
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.live import Live
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from ble_manager import BLEPeer
from config import load_contacts

console = Console()

class TerminalUI:
    def __init__(self, nickname: str):
        self.nickname = nickname
        self.messages = []
        self.peers: List[BLEPeer] = []
        self.active_channel = "BROADCAST"  # "BROADCAST" or target_device_id
        self.active_target_name = "Group Chat"
        self.status_msg = "Bluetooth Mesh Active"
        self.live: Optional[Live] = None

    def set_channel(self, target_id: str, target_name: str):
        self.active_channel = target_id
        self.active_target_name = target_name

    def add_message(self, sender: str, text: str, timestamp: str, is_self: bool = False, target_name: str = "ALL", hops: int = 1):
        self.messages.append({
            "sender": sender,
            "text": text,
            "timestamp": timestamp,
            "is_self": is_self,
            "target_name": target_name,
            "hops": hops
        })

    def update_peers(self, peers: List[BLEPeer]):
        self.peers = peers

    def update_status(self, status: str):
        self.status_msg = status

    def generate_layout(self) -> Layout:
        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3)
        )
        
        layout["main"].split_row(
            Layout(name="chat", ratio=3),
            Layout(name="sidebar", ratio=1)
        )

        # Header
        header_text = Text()
        header_text.append("📡 TERMINAL TALK ", style="bold cyan")
        header_text.append("│ ", style="dim")
        header_text.append(f"User: {self.nickname} ", style="bold green")
        header_text.append("│ ", style="dim")
        channel_style = "bold yellow" if self.active_channel == "BROADCAST" else "bold magenta"
        header_text.append(f"Channel: [{self.active_target_name}] ", style=channel_style)
        header_text.append("│ ", style="dim")
        header_text.append(f"Direct Peers: {len(self.peers)} ", style="bold blue")
        
        header_panel = Panel(header_text, border_style="cyan", title="Bluetooth Mesh Chat")
        layout["header"].update(header_panel)

        # Chat Feed
        chat_table = Table(show_header=False, box=None, expand=True)
        chat_table.add_column("Time", style="dim", width=8)
        chat_table.add_column("Target/Hops", style="dim cyan", width=14)
        chat_table.add_column("Sender", style="bold", width=15)
        chat_table.add_column("Message", style="white")

        # Filter messages for Group Chat or DM
        visible_messages = []
        for msg in self.messages:
            if self.active_channel == "BROADCAST":
                if msg["target_name"] == "ALL" or msg["is_self"]:
                    visible_messages.append(msg)
            else:
                # In DM mode with target_id
                if msg["target_name"] == self.active_target_name or msg["sender"] == self.active_target_name or msg["is_self"]:
                    visible_messages.append(msg)

        # Show last 15 messages
        for msg in visible_messages[-15:]:
            sender_style = "bold magenta" if msg["is_self"] else "bold green"
            sender_display = f"[{msg['sender']}]" if not msg["is_self"] else "[You]"
            
            hops_info = "Direct" if msg["hops"] <= 1 else f"Relay ({msg['hops']}H)"
            type_tag = f"[{msg['target_name'][:5]}│{hops_info}]"

            chat_table.add_row(
                msg["timestamp"],
                Text(type_tag, style="dim cyan"),
                Text(sender_display, style=sender_style),
                msg["text"]
            )

        chat_title = f"💬 {self.active_target_name} Messages"
        chat_panel = Panel(chat_table, title=chat_title, border_style="blue", padding=(0, 1))
        layout["chat"].update(chat_panel)

        # Sidebar (Direct Peers & Contact History)
        peer_table = Table(show_header=True, box=None, expand=True)
        peer_table.add_column("Contact", style="bold cyan")
        peer_table.add_column("Status", style="dim green")

        # Active direct peers
        direct_dev_ids = set()
        if self.peers:
            for p in self.peers:
                direct_dev_ids.add(p.device_id)
                signal = f"📶 {p.rssi}dBm" if p.rssi else "Direct"
                peer_table.add_row(f"{p.name[:10]}", signal)

        # Saved contacts history
        contacts = load_contacts()
        for dev_id, info in contacts.items():
            if dev_id not in direct_dev_ids and info.get("nickname") != self.nickname:
                peer_table.add_row(f"{info['nickname'][:10]}", "Mesh Relay")

        if not self.peers and not contacts:
            peer_table.add_row("Scanning...", "-")

        sidebar_panel = Panel(peer_table, title="📇 Contacts & Peers", border_style="magenta")
        layout["sidebar"].update(sidebar_panel)

        # Footer Status
        footer_text = Text(f" Status: {self.status_msg} │ Commands: /group, /chat <user>, /msg <user> <text>, /contacts", style="italic dim yellow")
        footer_panel = Panel(footer_text, border_style="dim")
        layout["footer"].update(footer_panel)

        return layout

    def render_snapshot(self):
        console.clear()
        console.print(self.generate_layout())
