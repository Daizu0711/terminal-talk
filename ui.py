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

def get_signal_display(peer: BLEPeer) -> str:
    if peer.peer_type == "LAN":
        return "🌐 LAN (Local)"
    
    conn_state = "🟢 Connected" if peer.is_connected else ("🟡 Pairing..." if peer.connecting else "⚪ Discovered")
    
    if peer.rssi >= -60:
        return f"{conn_state} 📶 Strong"
    elif peer.rssi >= -80:
        return f"{conn_state} 📶 Fair"
    else:
        return f"{conn_state} 📶 Weak"

class TerminalUI:
    def __init__(self, nickname: str):
        self.nickname = nickname
        self.messages = []
        self.peers: List[BLEPeer] = []
        self.active_channel = "#general"
        self.active_target_name = "#general"
        self.joined_channels: Set[str] = {"#general", "#mesh", "#dev"}
        self.unread_counts: Dict[str, int] = {}
        self.status_msg = "Bluetooth Talk Mesh Active"
        self.live: Optional[Live] = None

    def set_channel(self, channel_or_target: str, target_name: str):
        self.active_channel = channel_or_target
        self.active_target_name = target_name
        if target_name.startswith("#"):
            self.joined_channels.add(target_name)
        self.unread_counts[target_name] = 0

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
        msg_chan = channel if channel.startswith("#") else target_name
        if not is_self and msg_chan != self.active_target_name:
            self.unread_counts[msg_chan] = self.unread_counts.get(msg_chan, 0) + 1

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

        # Header - Channel Tabs with Badges
        header_text = Text()
        header_text.append("⚡ BLUETOOTH TALK ", style="bold bright_cyan")
        header_text.append("│ ", style="dim")
        header_text.append(f"<{self.nickname}> ", style="bold bright_green")
        header_text.append("│ Tabs: ", style="dim")

        all_tabs = list(self.joined_channels)
        for tab in all_tabs:
            unread = self.unread_counts.get(tab, 0)
            badge = f" (*{unread})" if unread > 0 else ""
            if tab == self.active_target_name:
                header_text.append(f"[{tab}{badge}] ", style="bold bright_black on yellow")
            else:
                tab_style = "bold bright_red" if unread > 0 else "dim cyan"
                header_text.append(f"[{tab}{badge}] ", style=tab_style)

        if not self.active_target_name.startswith("#"):
            header_text.append(f"[DM:{self.active_target_name}] ", style="bold bright_black on magenta")

        header_panel = Panel(header_text, border_style="cyan", title="Off-Grid Peer-to-Peer Bluetooth Mesh Terminal")
        layout["header"].update(header_panel)

        # Chat Log
        chat_table = Table(show_header=False, box=None, expand=True)
        chat_table.add_column("Time", style="dim", width=8)
        chat_table.add_column("Chan/Hops", style="dim cyan", width=14)
        chat_table.add_column("User", style="bold", width=15)
        chat_table.add_column("Message", style="white")

        visible_messages = []
        for msg in self.messages:
            if self.active_target_name.startswith("#"):
                if msg["channel"] == self.active_target_name or msg["target_name"] == "ALL" or msg["is_self"]:
                    visible_messages.append(msg)
            else:
                if msg["target_name"] == self.active_target_name or msg["sender"] == self.active_target_name or msg["is_self"]:
                    visible_messages.append(msg)

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

        # Sidebar - Numbered Peers & Connection Status
        peer_table = Table(show_header=True, box=None, expand=True)
        peer_table.add_column("#", style="dim yellow", width=2)
        peer_table.add_column("Peer Name", style="bold cyan")
        peer_table.add_column("Connection Status", style="dim green")

        if not self.peers:
            peer_table.add_row("-", "No peers found", "Scanning")
        else:
            for idx, p in enumerate(self.peers, 1):
                sig_str = get_signal_display(p)
                peer_table.add_row(str(idx), p.name[:12], sig_str)

        sidebar_panel = Panel(peer_table, title=f"📡 Connection Mesh ({len(self.peers)})", border_style="magenta")
        layout["sidebar"].update(sidebar_panel)

        # Footer Status
        footer_text = Text(f" Status: {self.status_msg} │ Shortcuts: /chat <#>, /connect <#>, /join <#chan>, /status, /quit", style="italic dim yellow")
        footer_panel = Panel(footer_text, border_style="dim")
        layout["footer"].update(footer_panel)

        return layout

    def render_snapshot(self):
        console.clear()
        console.print(self.generate_layout())
