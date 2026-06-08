import json
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer

from api_server.server import CbnRequestHandler


class DaemonApiTests(unittest.TestCase):
    def test_post_bad_json_returns_structured_error(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(
                f"{base_url}/call",
                data=b"{bad json",
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(raised.exception.code, 400)
            payload = json.loads(raised.exception.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_type"], "bad_request")
            self.assertEqual(payload["status"], 400)

    def test_options_returns_cors_headers(self):
        with daemon_url() as base_url:
            request = urllib.request.Request(f"{base_url}/call", method="OPTIONS")
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["ok"])
                self.assertEqual(response.headers["Access-Control-Allow-Methods"], "GET, POST, OPTIONS")
                self.assertEqual(response.headers["Access-Control-Allow-Headers"], "Content-Type")


@contextmanager
def daemon_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), CbnRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
