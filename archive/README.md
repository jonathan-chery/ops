# Operations

## Structure

```
infrastructure/
├── ops                           # Single executable entry point
├── configs/                      # App-specific variables
│   └── deep-research.env
├── lib/                          # Shared helper functions
│   ├── state.sh
│   ├── secrets.sh
│   └── proxmox.sh
└── phases/                       # Distinct execution steps
    ├── 01_preflight.sh
    ├── 02_teardown.sh
    ├── 03_create_ct.sh
    ├── 04_ssh_hardening.sh
    ├── 05_install_deps.sh
    ├── 06_deploy_app.sh
    ├── 07_systemd.sh
    └── 08_finalize.sh
```