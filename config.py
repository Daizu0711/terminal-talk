import json
import os
import socket
import time
import uuid

CONFIG_DIR = os.path.expanduser("~/.terminal-talk")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
CONTACTS_FILE = os.path.join(CONFIG_DIR, "contacts.json")

# 128-bit custom Service & Characteristic UUIDs for Terminal Talk (BitChat Protocol compatible)
SERVICE_UUID = "9A2F3B8C-4D1E-4F2A-9B8C-1D2E3F4A5B6C"
CHARACTERISTIC_UUID_MSG = "9A2F3B8C-4D1E-4F2A-9B8C-1D2E3F4A5B6D"

DEFAULT_CONFIG = {
    "nickname": f"User-{socket.gethostname().split('.')[0]}",
    "device_id": str(uuid.uuid4())[:8],
    "default_channel": "#general",
    "service_uuid": SERVICE_UUID,
    "char_uuid": CHARACTERISTIC_UUID_MSG
}

def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)

def load_config() -> dict:
    ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(data)
                return config
        except Exception:
            pass
    
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()

def save_config(config: dict):
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def load_contacts() -> dict:
    ensure_config_dir()
    if os.path.exists(CONTACTS_FILE):
        try:
            with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_contacts(contacts: dict):
    ensure_config_dir()
    with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
        json.dump(contacts, f, indent=2, ensure_ascii=False)

def update_contact(device_id: str, nickname: str, address: str = ""):
    contacts = load_contacts()
    contacts[device_id] = {
        "device_id": device_id,
        "nickname": nickname,
        "address": address,
        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    save_contacts(contacts)

def panic_wipe_data():
    """BitChat Panic Mode: Wipes all local configuration, message history, and saved contacts."""
    try:
        if os.path.exists(CONFIG_FILE):
            os.remove(CONFIG_FILE)
        if os.path.exists(CONTACTS_FILE):
            os.remove(CONTACTS_FILE)
        return True
    except Exception:
        return False
