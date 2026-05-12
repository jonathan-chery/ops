# Secrets Management

Ops encrypts secrets at rest using Fernet (AES-128 in CBC mode via `cryptography`) with a master key stored in your OS keyring.

## Master Key Storage

1. **Primary:** OS keyring (Linux: SecretStorage via D-Bus; macOS: Keychain; Windows: Credential Manager)
2. **Fallback:** `~/.ops/.master_key` (file, 0o600 permissions, warning logged on use)

## Secret Types

| Type | Description | Example |
|---|---|---|
| `generated` | Cryptographically random string | Passwords, API keys |
| `prompt` | Interactive hidden input | Manual secrets |
| `file` | Read from local file | TLS certificates |
| `infisical` | Fetch from Infisical (optional) | Team-shared secrets |

## Generated Secrets

```yaml
secrets:
  - name: DB_PASSWORD
    type: generated
    length: 48
    charset: alphanumeric  # alphanumeric, hex, base64
```

Generated once and persisted in `DeploymentState.secrets_resolved`. Rotation:

```bash
ops rotate-secrets myapp  # Regenerates all generated secrets
```

## Prompt Secrets

```yaml
secrets:
  - name: API_KEY
    type: prompt
    description: "Enter your OpenAI API key"
```

The prompt appears once during first deployment and is cached encrypted.

## Infisical Integration

```yaml
secrets:
  - name: STRIPE_KEY
    type: infisical
    path: /production/payments
    key: stripe_live_key
    required: true
```

Requires `infisical` block in `~/.ops/config.yaml`:

```yaml
infisical:
  client_id: ENC[...]
  client_secret: ENC[...]
  url: https://app.infisical.com
```

## Encryption Details

- **Algorithm:** Fernet (AES-128-CBC + HMAC-SHA256)
- **KDF:** PBKDF2HMAC with 100,000 iterations, SHA256
- **Salt:** Per-file random 16 bytes
- **Key:** 32-byte base64-encoded Fernet key

## SSH Key Lifecycle

Every deployment gets two Ed25519 keypairs:

| Key | User | Purpose |
|---|---|---|
| `root` | `root@container` | Administrative access |
| `app` | App user (`native` deployments) | Application runtime access |

Keys are stored in `~/.ops/secrets/{app_name}/`:

```
~/.ops/secrets/myapp/
├── root          # Private key (0o600)
├── root.pub      # Public key
├── app           # Private key (0o600)
└── app.pub       # Public key
```

Rotation:

```bash
ops rotate-ssh myapp
```

Replaces both keypairs and updates authorized_keys inside the container.
