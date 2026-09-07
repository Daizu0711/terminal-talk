import http.server
import os
import socket
import socketserver
import sys
import time

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"

def run_share_server(port=8080):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ip = get_local_ip()

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=script_dir, **kwargs)
        def log_message(self, format, *args):
            print(f"[{time.strftime('%H:%M:%S')}] Shared file with friend: {args[0]}")

    print("\n=====================================================")
    print("🚀 Share Terminal Talk Server Running!\n")
    print("Send one of these commands to your friend's terminal:\n")
    print(f"📌 Local Wi-Fi Network Command:")
    print(f"   curl -fsSL http://{ip}:{port}/install.sh | bash\n")
    print(f"📌 GitHub Command (After pushing to GitHub):")
    print(f"   curl -fsSL https://raw.githubusercontent.com/Daizu0711/terminal-talk/main/install.sh | bash")
    print("\n=====================================================")
    print("🌐 Sharing server is LIVE. Press Ctrl+C to stop.\n")

    try:
        with socketserver.TCPServer(("", port), QuietHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nSharing server stopped.")
    except Exception as e:
        print(f"\nServer error: {e}")

if __name__ == "__main__":
    run_share_server()
