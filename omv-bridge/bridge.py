#!/usr/bin/env python3

import json
import os
import socketserver
import subprocess
import threading

from http.server import BaseHTTPRequestHandler


SOCKET_PATH = os.getenv(
    "KYBER_BRIDGE_SOCKET",
    "/run/kyber-omv/bridge.sock"
)

OMV_RPC = "/usr/sbin/omv-rpc"
MAX_BODY = 1024 * 1024


def omv_rpc(method, params):
    cmd = [
        OMV_RPC,
        "-u", "admin",
        "Compose",
        method,
        json.dumps(params),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(
            (
                result.stderr
                or result.stdout
                or "OMV RPC failed"
            ).strip()
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"output": result.stdout.strip()}


class Handler(BaseHTTPRequestHandler):

    server_version = "KyberOMVBridge/2.0"

    def address_string(self):
        try:
            return super().address_string()
        except Exception:
            return "local"

    def log_message(self, fmt, *args):
        print(
            "%s - %s" %
            (self.address_string(), fmt % args),
            flush=True,
        )

    def send_json(self, status, data):
        body = json.dumps(data).encode()

        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json"
        )
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.end_headers()

        self.wfile.write(body)

    def read_json(self):
        try:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )
        except ValueError:
            raise ValueError(
                "Invalid Content-Length"
            )

        if length <= 0:
            return {}

        if length > MAX_BODY:
            raise ValueError(
                "Request too large"
            )

        raw = self.rfile.read(length)

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError(
                "Invalid JSON"
            )

    def do_GET(self):

        if self.path == "/health":
            try:
                # Verify that OpenMediaVault and the Compose plugin
                # can answer a harmless read request.
                omv_rpc(
                    "getFileList",
                    {
                        "start": 0,
                        "limit": 1,
                        "sortfield": "name",
                        "sortdir": "ASC",
                    },
                )

                self.send_json(
                    200,
                    {
                        "status": "ok",
                        "service":
                            "kyber-omv-bridge",
                        "transport":
                            "unix-socket",
                        "version": "2.0",
                        "openmediavault": True,
                        "compose_plugin": True,
                    },
                )

            except Exception as exc:
                self.send_json(
                    503,
                    {
                        "status": "unavailable",
                        "service":
                            "kyber-omv-bridge",
                        "error": str(exc),
                    },
                )

            return

        if self.path == "/compose/files":
            try:
                result = omv_rpc(
                    "getFileList",
                    {
                        "start": 0,
                        "limit": 1000,
                        "sortfield": "name",
                        "sortdir": "ASC",
                    },
                )

                self.send_json(
                    200,
                    result
                )

            except Exception as exc:
                self.send_json(
                    500,
                    {"error": str(exc)},
                )

            return

        self.send_json(
            404,
            {"error": "Not found"}
        )

    def do_POST(self):

        try:
            data = self.read_json()

            if self.path == "/compose/register":

                allowed = {
                    "name",
                    "description",
                    "body",
                    "showenv",
                    "env",
                    "showoverride",
                    "override",
                }

                if set(data) - allowed:
                    raise ValueError(
                        "Unsupported fields"
                    )

                name = str(
                    data.get("name", "")
                ).strip()

                body = str(
                    data.get("body", "")
                )

                if not name:
                    raise ValueError(
                        "name is required"
                    )

                if not body:
                    raise ValueError(
                        "body is required"
                    )

                params = {
                    "name": name,
                    "description": str(
                        data.get(
                            "description",
                            ""
                        )
                    ),
                    "body": body,
                    "showenv": bool(
                        data.get(
                            "showenv",
                            False
                        )
                    ),
                    "env": str(
                        data.get(
                            "env",
                            ""
                        )
                    ),
                    "showoverride": bool(
                        data.get(
                            "showoverride",
                            False
                        )
                    ),
                    "override": str(
                        data.get(
                            "override",
                            ""
                        )
                    ),
                }

                result = omv_rpc(
                    "setFile",
                    params
                )

                self.send_json(
                    200,
                    result
                )
                return

            if self.path == "/compose/delete":

                uuid = str(
                    data.get(
                        "uuid",
                        ""
                    )
                ).strip()

                if not uuid:
                    raise ValueError(
                        "uuid is required"
                    )

                result = omv_rpc(
                    "deleteFile",
                    {"uuid": uuid},
                )

                self.send_json(
                    200,
                    result
                )
                return

            self.send_json(
                404,
                {"error": "Not found"},
            )

        except ValueError as exc:
            self.send_json(
                400,
                {"error": str(exc)},
            )

        except subprocess.TimeoutExpired:
            self.send_json(
                504,
                {"error": "OMV RPC timed out"},
            )

        except Exception as exc:
            self.send_json(
                500,
                {"error": str(exc)},
            )


class ThreadingUnixHTTPServer(
    socketserver.ThreadingMixIn,
    socketserver.UnixStreamServer,
):
    daemon_threads = True



if __name__ == "__main__":

    os.makedirs(
        os.path.dirname(SOCKET_PATH),
        exist_ok=True,
    )

    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    unix_server = ThreadingUnixHTTPServer(
        SOCKET_PATH,
        Handler,
    )

    os.chmod(SOCKET_PATH, 0o600)

    print(
        f"Kyber OMV bridge listening on "
        f"{SOCKET_PATH}",
        flush=True,
    )


    try:
        unix_server.serve_forever()
    finally:
        unix_server.server_close()

        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
