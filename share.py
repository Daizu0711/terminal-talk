import http.server
import os
import socket
import socketserver
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
    base_url = f"http://{ip}:{port}"

    class DynamicHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=script_dir, **kwargs)
        
        def do_GET(self):
            if self.path == "/install.sh":
                install_path = os.path.join(script_dir, "install.sh")
                if os.path.exists(install_path):
                    with open(install_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    # Inject local server URL header
                    injected_content = f"export HTTP_SHARE_URL=\"{base_url}\"\n" + content
                    encoded = injected_content.encode("utf-8")
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "text/x-shellscript")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
            super().do_GET()

        def log_message(self, format, *args):
            print(f"[{time.strftime('%H:%M:%S')}] Shared component with friend: {args[0]}")

    print("\n=====================================================")
    print("🚀 Share Terminal Talk Server Running!\n")
    print("Send one of these commands to your friend's terminal:\n")
    print(f"📌 Local Wi-Fi Network Command (No GitHub needed!):")
    print(f"   curl -fsSL {base_url}/install.sh | bash\n")
    print(f"📌 GitHub Command (Public internet):")
    print(f"   curl -fsSL https://raw.githubusercontent.com/Daizu0711/terminal-talk/main/install.sh | bash")
    print("\n=====================================================")
    print("🌐 Sharing server is LIVE. Keep this window open!")
    print("   Press Ctrl+C to stop sharing server.\n")

    try:
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", port), DynamicHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nSharing server stopped.")
    except Exception as e:
        print(f"\nServer error: {e}")

if __name__ == "__main__":
    run_share_server()
