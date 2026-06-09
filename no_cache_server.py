"""
no_cache_server.py
- Cache-Control: no-cache, no-store, must-revalidate 헤더를 모든 응답에 삽입
- 브라우저가 항상 최신 파일을 서버에서 받아오도록 강제
"""
import http.server
import socketserver
import os

PORT = 3000
DIRECTORY = os.path.join(os.path.dirname(__file__), "frontend")

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, format, *args):
        # 로그 간소화
        pass

print(f"[ITDA Frontend] No-Cache Server running at http://localhost:{PORT}")
print(f"[ITDA Frontend] Serving from: {DIRECTORY}")

with socketserver.TCPServer(("", PORT), NoCacheHandler) as httpd:
    httpd.serve_forever()
