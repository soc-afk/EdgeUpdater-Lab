import os
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HOST = "0.0.0.0"
PORT = 8080
BASE = Path.home() / "lab-transfer"
DOWNLOADS = BASE / "downloads"
UPLOADS = BASE / "uploads"
MAX_SIZE = 10 * 1024 * 1024  # 10 MiB

DOWNLOADS.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)


def safe_filename(path):
    name = unquote(urlparse(path).path).lstrip("/")
    if not name or Path(name).name != name or name in (".", ".."):
        return None
    return name


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        name = safe_filename(self.path)
        if not name:
            self.send_error(400, "Provide a filename")
            return

        target = DOWNLOADS / name
        if not target.is_file():
            self.send_error(404, "Download not found")
            return

        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_upload(self):
        """Validate filename and body. Returns (name, data) or None after sending an error."""
        name = safe_filename(self.path)
        if not name:
            self.send_error(400, "Provide a filename")
            return None

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid content length")
            return None

        if length <= 0 or length > MAX_SIZE:
            self.send_error(413, "Upload must be 1 byte to 10 MiB")
            return None

        data = self.rfile.read(length)
        if len(data) != length:
            self.send_error(400, "Incomplete upload")
            return None

        return name, data

    def _respond(self, code, message):
        body = (message + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        result = self._read_upload()
        if not result:
            return
        name, data = result

        target = UPLOADS / name
        try:
            # "xb" fails atomically if the file exists, avoiding a check-then-write race
            with open(target, "xb") as f:
                f.write(data)
        except FileExistsError:
            self.send_error(409, "File already exists")
            return

        self._respond(201, "Upload successful")

    def do_PUT(self):
        result = self._read_upload()
        if not result:
            return
        name, data = result

        target = UPLOADS / name
        existed = target.exists()

        # Write to a temp file, then atomically swap it in so readers
        # never see a partially written file
        fd, tmp_path = tempfile.mkstemp(dir=UPLOADS)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp_path, target)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        if existed:
            self._respond(200, "File replaced")
        else:
            self._respond(201, "Upload successful")

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - {fmt % args}")


print(f"Listening on http://{HOST}:{PORT}")
print(f"Download directory: {DOWNLOADS}")
print(f"Upload directory:   {UPLOADS}")

HTTPServer((HOST, PORT), Handler).serve_forever()
