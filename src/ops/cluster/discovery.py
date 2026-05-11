"""Cluster auto-discovery and node registry."""

import json
import hmac
import hashlib
import socket
import struct
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from ops.models.cluster import OpsNode, ClusterConfig

UDP_BROADCAST_PORT = 9876
UDP_MAGIC = b"OPS_BEACON"


class DiscoveryService:
    """UDP-based auto-discovery with HMAC authentication.

    Nodes broadcast signed JSON beacons on a well-known UDP port.
    Peers verify the HMAC using a shared cluster secret before
    adding the sender to the node registry.
    """

    def __init__(self, config: ClusterConfig, node_id: Optional[str] = None):
        self.config = config
        self.node_id = node_id or self._load_or_create_node_id()
        self._secret = self._derive_key(config.secret or "")

    def _load_or_create_node_id(self) -> str:
        path = Path("~/.ops/node_id").expanduser()
        if path.exists():
            return path.read_text().strip()
        nid = str(uuid.uuid4())
        path.write_text(nid)
        return nid

    def _derive_key(self, secret: str) -> bytes:
        """Normalize shared secret to a 32-byte HMAC key."""
        return hashlib.sha256(secret.encode()).digest()

    def _sign_payload(self, payload: bytes) -> bytes:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest().encode()

    def _verify_payload(self, payload: bytes, sig: bytes) -> bool:
        expected = self._sign_payload(payload)
        return hmac.compare_digest(expected, sig)

    def _build_beacon(self, advertise_port: int = 8443) -> bytes:
        """Construct a signed UDP beacon packet."""
        payload = json.dumps(
            {
                "node_id": self.node_id,
                "name": socket.gethostname(),
                "api_port": advertise_port,
                "transport": self.config.transport,
                "labels": self.config.labels,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
            separators=(",", ":"),
        ).encode()
        sig = self._sign_payload(payload)
        return UDP_MAGIC + struct.pack("!I", len(payload)) + payload + b"\n" + sig

    def _parse_beacon(self, data: bytes) -> Optional[Dict]:
        """Parse and verify a UDP beacon."""
        if not data.startswith(UDP_MAGIC):
            return None
        offset = len(UDP_MAGIC)
        if len(data) < offset + 4:
            return None
        plen = struct.unpack("!I", data[offset : offset + 4])[0]
        offset += 4
        payload = data[offset : offset + plen]
        rest = data[offset + plen :]
        if not rest.startswith(b"\n"):
            return None
        sig = rest[1:]
        if not self._verify_payload(payload, sig):
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def send_beacon(self, advertise_port: int = 8443) -> None:
        """Broadcast a single beacon packet."""
        packet = self._build_beacon(advertise_port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            try:
                sock.sendto(packet, ("255.255.255.255", self.config.advertise_port))
            except OSError:
                pass  # Network may not support broadcast

    def listen(self, timeout: float = 5.0) -> List[OpsNode]:
        """Listen for beacons and return a list of discovered nodes."""
        nodes: List[OpsNode] = []
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", self.config.advertise_port))
            except OSError:
                return nodes  # Port in use
            sock.settimeout(timeout)
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(2048)
                except socket.timeout:
                    break
                parsed = self._parse_beacon(data)
                if parsed:
                    nodes.append(
                        OpsNode(
                            node_id=parsed["node_id"],
                            name=parsed["name"],
                            host=addr[0],
                            api_port=parsed.get("api_port"),
                            transport=parsed.get("transport", "ssh"),
                            fingerprint="",  # Filled in by dialback verification
                            labels=parsed.get("labels", {}),
                        )
                    )
        return nodes
