# Guide: Multi-Node Cluster

Deploy workloads across multiple Proxmox nodes with auto-discovery.

## Step 1: Join Cluster on Each Node

On `pve1`:

```bash
ops cluster-join --transport ssh --label "compute"
```

On `pve2`:

```bash
ops cluster-join --transport ssh --label "gpu"
```

## Step 2: Verify Discovery

On any node:

```bash
ops cluster-status
```

Output:

```
Node            Transport   Labels      Last Seen
pve1            ssh         compute     5s ago
pve2            ssh         gpu         12s ago
```

## Step 3: Deploy with Auto-Placement

```bash
ops deploy myapp --cluster
```

Ops picks the node with the lowest container count. To force placement on a GPU node:

```yaml
container:
  node_constraints:
    - gpu
```

## Node Constraints

Add labels to your blueprint to constrain placement:

```yaml
container:
  hostname: ml-worker
  cores: 8
  memory: 32768
  node_constraints:
    - gpu
    - compute
```

Ops matches `node_constraints` against discovered node labels. The first node that matches all constraints and has capacity wins.

## Transport: HTTPS

If SSH key exchange is not possible, use HTTPS:

```bash
ops cluster-join --transport https --host https://pve2.local:8006
```

This requires API tokens in `config.yaml` for each host.
