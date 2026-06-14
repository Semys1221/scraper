import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import auto_run

PORT = int(os.getenv("PORT", 8001))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, format, *args):
        pass


def start_http():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"[MAIN] Health server on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    auto_run()
