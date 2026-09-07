import http.server
import os
import socket
import socketserver
import sys
import threading

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

def start_local_share_server(port=8080):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=script_dir, **kwargs)
        def log_message(self, format, *args):
            pass

    try:
        httpd = socketserver.TCPServer(("", port), QuietHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return port
    except Exception:
        return None

def print_share_info():
    ip = get_local_ip()
    port = start_local_share_server(8080)
    
    print("\n=====================================================")
    print("🚀 Share Terminal Talk with nearby friends!\n")
    print("Copy and send one of the following commands to your friend:")
    
    if port:
        print(f"\n📌 If on the same Wi-Fi / Local Network:")
        print(f"   curl -fsSL http://{ip}:{port}/install.sh | bash")

    print(f"\n📌 If sharing via GitHub / Direct File:")
    print("   curl -fsSL https://raw.githubusercontent.com/Daizu0711/terminal-talk/main/install.sh | bash")
    print("\n=====================================================\n")

if __name__ == "__main__":
    print_share_info()
