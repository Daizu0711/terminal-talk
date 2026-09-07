import asyncio
import os
import sys
import time
from typing import Dict, List, Optional, Set
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
        self.active_channel = "#general"  # "#general", "#mesh", or target_device_id
        self.active_target_name = "#general"
        self.joined_channels: Set[str] = {"#general", "#mesh", "#dev"}
        self.status_msg = "Bluetooth Talk Mesh Active"
        self.live: Optional[Live] = None

    def set_channel(self, channel_or_target: str, target_name: str):
        self.active_channel = channel_or_target
        self.active_target_name = target_name
        if target_name.startswith("#"):
            self.joined_channels.add(target_name)

    def add_message(self, sender: str, text: str, timestamp: str, is_self: bool = False, channel: str = "#general", target_name: str = "ALL", hops: int = 1):
        self.messages.append({
            "sender": sender,
            "text": text,
            "timestamp": timestamp,
            "is_self": is_self,
            "channel": channel,
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

        # Header - Bluetooth Talk Style
        header_text = Text()
        header_text.append("⚡ BLUETOOTH TALK ", style="bold bright_cyan")
        header_text.append("│ ", style="dim")
        header_text.append(f"Nick: <{self.nickname}> ", style="bold bright_green")
        header_text.append("│ ", style="dim")
        channel_style = "bold bright_yellow" if self.active_target_name.startswith("#") else "bold bright_magenta"
        header_text.append(f"Channel: {self.active_target_name} ", style=channel_style)
        header_text.append("│ ", style="dim")
        header_text.append(f"Peers: {len(self.peers)} ", style="bold bright_blue")
        
        header_panel = Panel(header_text, border_style="cyan", title="Off-Grid Peer-to-Peer Bluetooth Mesh Terminal")
        layout["header"].update(header_panel)

        # Chat Feed - Classic IRC Log Format (<User> Message)
        chat_table = Table(show_header=False, box=None, expand=True)
        chat_table.add_column("Time", style="dim", width=8)
        chat_table.add_column("Chan/Hops", style="dim cyan", width=14)
        chat_table.add_column("User", style="bold", width=15)
        chat_table.add_column("Message", style="white")

        visible_messages = []
        for msg in self.messages:
            if self.active_target_name.startswith("#"):
                # Channel mode
                if msg["channel"] == self.active_target_name or msg["target_name"] == "ALL" or msg["is_self"]:
                    visible_messages.append(msg)
            else:
                # Direct Message mode
                if msg["target_name"] == self.active_target_name or msg["sender"] == self.active_target_name or msg["is_self"]:
                    visible_messages.append(msg)

        # Show last 15 messages
        for msg in visible_messages[-15:]:
            sender_style = "bold magenta" if msg["is_self"] else "bold green"
            sender_display = f"<{msg['sender']}>" if not msg["is_self"] else "<You>"
            
            hops_info = "Local" if msg["hops"] <= 1 else f"{msg['hops']}H"
            chan_info = msg["channel"] if msg["channel"].startswith("#") else "DM"
            tag = f"[{chan_info}│{hops_info}]"

            chat_table.add_row(
                msg["timestamp"],
                Text(tag, style="dim cyan"),
                Text(sender_display, style=sender_style),
                msg["text"]
            )

        chat_title = f"💬 {self.active_target_name} Activity"
        chat_panel = Panel(chat_table, title=chat_title, border_style="blue", padding=(0, 1))
        layout["chat"].update(chat_panel)

        # Sidebar - BitChat Channels & Mesh Peers
        sidebar_table = Table(show_header=True, box=None, expand=True)
        sidebar_table.add_column("IRC Channels", style="bold yellow")
        sidebar_table.add_column("Peers", style="bold cyan")

        channel_list = list(self.joined_channels)
        peer_list = [f"{p.name[:14]} ({p.peer_type})" for p in self.peers] if self.peers else ["Scanning..."]

        max_rows = max(len(channel_list), len(peer_list))
        for i in range(max_rows):
            ch = channel_list[i] if i < len(channel_list) else ""
            pr = peer_list[i] if i < len(peer_list) else ""
            sidebar_table.add_row(ch, pr)

        sidebar_panel = Panel(sidebar_table, title="📡 Network & Channels", border_style="magenta")
        layout["sidebar"].update(sidebar_panel)

        # Footer Status
        footer_text = Text(f" Status: {self.status_msg} │ IRC Commands: /join <#chan>, /msg <user> <msg>, /who, /panic, /quit", style="italic dim yellow")
        footer_panel = Panel(footer_text, border_style="dim")
        layout["footer"].update(footer_panel)

        return layout

    def render_snapshot(self):
        console.clear()
        console.print(self.generate_layout())
