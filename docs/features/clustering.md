# Clustering

Ops can discover and manage a cluster of Proxmox nodes for workload distribution.

## Discovery

Nodes announce themselves via UDP broadcasts on port `53535`:

```bash
ops cluster-join --transport ssh --label "gpu"
```

This starts a background discovery beacon. Other nodes within the same subnet auto-register.

## Node Registry

Discovered nodes are stored in `~/.ops/state/cluster.json`:

```json
{
  "nodes": [
    {
      "id": "pve1-aabbccdd",
      "hostname": "pve1",
      "address": "10.0.0.10",
      "transport": "ssh",
      "labels": ["gpu", "compute"],
      "last_seen": "2026-05-12T10:00:00Z"
    }
  ]
}
```

## Cluster Status

```bash
ops cluster-status
```

Shows all discovered nodes, their transport, labels, and last-seen timestamp.

## Auto-Placement

When deploying with `--cluster`, Ops picks the best node based on:

1. **Capacity** (fewest containers per node)
2. **Labels** (match blueprint `node_constraints`)
3. **Health** (last-seen within 60 seconds)

```bash
ops deploy myapp --cluster
```

## Transports

| Transport | Port | Security |
|---|---|---|
| `ssh` | 22 | Key-based, no passwords stored |
| `https` | 8006 | API token + TLS verification (optional) |

Switch transport for a node:

```bash
ops cluster-join --transport https --host https://pve2.local:8006
```

## Leaving the Cluster

```bash
ops cluster-leave
```

Stops the local beacon and removes the node from all peer registries.
