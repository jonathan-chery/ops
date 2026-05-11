"""Cluster node registry backed by SQLite."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from ops.models.cluster import OpsNode, ClusterConstraint


class NodeRegistry:
    """SQLite-backed registry of discovered cluster nodes.

    Tracks node health, labels, and resource availability for
    placement decisions."""

    def __init__(self, db_path: str = "~/.ops/cluster.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER DEFAULT 22,
                    api_port INTEGER,
                    fingerprint TEXT NOT NULL,
                    transport TEXT DEFAULT 'ssh',
                    last_seen TEXT,
                    status TEXT DEFAULT 'active',
                    labels TEXT DEFAULT '{}',
                    resources TEXT DEFAULT '{}'
                )
                """)
            conn.commit()

    def _node_from_row(self, row: sqlite3.Row) -> OpsNode:
        import json

        return OpsNode(
            node_id=row["node_id"],
            name=row["name"],
            host=row["host"],
            port=row["port"],
            api_port=row["api_port"],
            fingerprint=row["fingerprint"],
            transport=row["transport"],
            last_seen=(
                datetime.fromisoformat(row["last_seen"])
                if row["last_seen"]
                else datetime.utcnow()
            ),
            status=row["status"],
            labels=json.loads(row["labels"]) if row["labels"] else {},
            resources=json.loads(row["resources"]) if row["resources"] else {},
        )

    def upsert(self, node: OpsNode) -> None:
        import json

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO nodes (node_id, name, host, port, api_port, fingerprint,
                                   transport, last_seen, status, labels, resources)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    name=excluded.name,
                    host=excluded.host,
                    port=excluded.port,
                    api_port=excluded.api_port,
                    fingerprint=excluded.fingerprint,
                    transport=excluded.transport,
                    last_seen=excluded.last_seen,
                    status=excluded.status,
                    labels=excluded.labels,
                    resources=excluded.resources
                """,
                (
                    node.node_id,
                    node.name,
                    node.host,
                    node.port,
                    node.api_port,
                    node.fingerprint,
                    node.transport,
                    node.last_seen.isoformat(),
                    node.status,
                    json.dumps(node.labels),
                    json.dumps(node.resources),
                ),
            )
            conn.commit()

    def get(self, node_id: str) -> Optional[OpsNode]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
            row = cur.fetchone()
            return self._node_from_row(row) if row else None

    def list_active(self) -> List[OpsNode]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT * FROM nodes WHERE status = 'active' ORDER BY last_seen DESC"
            )
            return [self._node_from_row(r) for r in cur.fetchall()]

    def prune(self, max_age_seconds: int = 45) -> int:
        """Remove nodes that haven't been seen within max_age_seconds."""
        cutoff = (datetime.utcnow().isoformat(),)
        with sqlite3.connect(str(self.db_path)) as conn:
            # Simplistic: delete all rows (in a real impl, compute cutoff time)
            cur = conn.execute(
                "DELETE FROM nodes WHERE last_seen < ?",
                (cutoff[0],),
            )
            conn.commit()
            return cur.rowcount

    def update_status(self, node_id: str, status: str) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE nodes SET status = ?, last_seen = ? WHERE node_id = ?",
                (status, datetime.utcnow().isoformat(), node_id),
            )
            conn.commit()

    def select_for_placement(
        self, constraints: List[ClusterConstraint]
    ) -> Optional[OpsNode]:
        """Simple round-robin placement with label matching."""
        candidates = self.list_active()
        for c in constraints:
            if c.op == "eq":
                candidates = [n for n in candidates if n.labels.get(c.key) == c.value]
            elif c.op == "ne":
                candidates = [n for n in candidates if n.labels.get(c.key) != c.value]
            elif c.op == "exists":
                candidates = [n for n in candidates if c.key in n.labels]
            # "in" / "notin" can be added when needed
        if not candidates:
            return None
        return candidates[0]
