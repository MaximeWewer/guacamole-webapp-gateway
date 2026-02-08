# Guacamole WebApp Gateway

Extend Apache Guacamole with web application support. This project adds a **Session Broker** that provisions isolated browser containers (Firefox/Chromium) per user, enabling secure access to internal web applications through Guacamole's clientless remote desktop interface.

**Turn Guacamole into a web application gateway** - users connect via their browser to access corporate webapps in isolated, pre-configured environments with managed bookmarks, secret autofill, and session recording.

## Overview

Traditional Guacamole provides RDP/VNC/SSH access to full desktops and servers. This project adds a new use case: **web application access** through lightweight browser containers.

When a user logs in, the broker automatically provisions a dedicated VNC container running only a web browser. The browser is pre-configured with:

- **Managed bookmarks** pointing to internal web applications
- **Homepage** set to the primary webapp
- **Credential autofill** for login pages (with Vault integration)
- **Enterprise browser policies** (no downloads, restricted settings, etc.)

### Use cases

- **Internal webapp access** - Provide browser-based access to intranet applications
- **Contractor/vendor access** - Secure, isolated browsing without VPN or device enrollment
- **BYOD environments** - Access corporate webapps from any device with a browser
- **Compliance & audit** - Session recording for regulated environments
- **Kiosk mode** - Locked-down browser access to specific applications

### Key features

- **Web application gateway** - Access internal webapps through Guacamole's interface
- **Isolated browser containers** - Each user gets a dedicated Firefox/Chromium instance
- **Group-based profiles** - Bookmarks, homepage, and autofill from Guacamole user groups
- **Credential autofill** - Pre-fill login forms with Vault-stored secrets
- **Session recording** - Record browser sessions for audit/compliance (Guacamole 1.5+)
- **Container pre-warming** - Pool of ready containers for instant connections
- **Auto-provisioning** - Containers created/destroyed based on user activity
- **Enterprise policies** - Firefox/Chromium managed policies for lockdown

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    STEP 1: guacamole-helm                      │
│  (from https://github.com/MaximeWewer/guacamole-helm)          │
├────────────────────────────────────────────────────────────────┤
│  - Guacamole Client (webapp)                                   │
│  - Guacd (protocol server)                                     │
│  - PostgreSQL (database)                                       │
│  - Ingress (optional)                                          │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                    STEP 2: guacamole-broker                    │
│  (this chart - standalone deployment)                          │
├────────────────────────────────────────────────────────────────┤
│  - Session Broker (Flask API)                                  │
│  - RBAC for VNC pod management                                 │
│  - ConfigMap (broker.yml, profiles.yml)                        │
│  - Secret (Guacamole credentials)                              │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│                    VNC Pods (spawned by broker)                │
├────────────────────────────────────────────────────────────────┤
│  - Per-user browser containers                                 │
│  - Firefox ESR or Chromium                                     │
│  - Managed bookmarks and policies                              │
└────────────────────────────────────────────────────────────────┘
```

### Components

| Service            | Description                                     |
| ------------------ | ----------------------------------------------- |
| **guacamole**      | Apache Guacamole web application                |
| **guacd**          | Guacamole protocol server (VNC gateway)         |
| **session-broker** | Python service managing container lifecycle     |
| **postgres**       | Database for Guacamole and broker state         |
| **VNC pods**       | Per-user browser instances for webapp access    |

## Requirements

- Kubernetes 1.25+
- Helm 3.x
- [guacamole-helm](https://github.com/MaximeWewer/guacamole-helm) deployed
- 4GB RAM minimum (8GB+ recommended for multiple users)

## Quick start

### 1. Deploy Guacamole first

```bash
# Add the Guacamole Helm repository
helm repo add guacamole https://maximewewer.github.io/guacamole-helm
helm repo update

# Install Guacamole
helm install guacamole guacamole/guacamole \
  --namespace guacamole \
  --create-namespace \
  --set postgresql.enabled=true
```

### 2. Get PostgreSQL password

```bash
PGPASSWORD=$(kubectl get secret guacamole-postgresql -n guacamole \
  -o jsonpath='{.data.password}' | base64 -d)
```

### 3. Deploy the Session Broker

```bash
# Clone this repository
git clone https://github.com/MaximeWewer/guacamole-webapp-gateway.git
cd guacamole-webapp-gateway

# Install the broker
helm install broker ./chart \
  --namespace guacamole \
  --set guacamole.url=http://guacamole:8080/guacamole \
  --set guacamole.adminPassword=guacadmin \
  --set database.host=guacamole-postgresql \
  --set database.password=$PGPASSWORD
```

### 4. Verify deployment

```bash
# Check pods
kubectl get pods -n guacamole -l app.kubernetes.io/name=guacamole-broker

# Check logs
kubectl logs -n guacamole -l app.kubernetes.io/name=guacamole-broker

# Test health endpoint
kubectl port-forward -n guacamole svc/broker-guacamole-broker 5000:5000
curl http://localhost:5000/health
```

## Configuration

### Helm values

The broker is configured via `values.yaml`. Key sections:

```yaml
# Connection to existing Guacamole deployment
guacamole:
  url: "http://guacamole:8080/guacamole"
  adminUser: guacadmin
  adminPassword: ""
  existingSecret: ""  # Use existing secret instead

# Connection to PostgreSQL
database:
  host: "guacamole-postgresql"
  port: 5432
  name: "guacamole"
  user: "guacamole"
  password: ""
  existingSecret: ""  # Use existing secret instead

# VNC container configuration
vnc:
  image:
    repository: ghcr.io/maximewewer/docker-browser-vnc
    tag: 2026.01.2-chromium
  resources:
    requests: { memory: "512Mi", cpu: "250m" }
    limits: { memory: "2Gi", cpu: "1000m" }

# User profiles (bookmarks, homepage, autofill)
profiles:
  default:
    description: "Default profile"
    priority: 0
    homepage: "https://www.google.com"
    bookmarks:
      - name: "Google"
        url: "https://www.google.com"
```

See `chart/values.yaml` for the complete list of options.

### User profiles

Profiles define browser configuration per Guacamole user group:

```yaml
profiles:
  developers:
    description: "Development team"
    priority: 10
    homepage: "https://github.com"
    bookmarks:
      - name: "GitHub"
        url: "https://github.com"
      - name: "Stack Overflow"
        url: "https://stackoverflow.com"
    autofill:
      - url: "https://github.com/login"
        username: "${GUAC_USERNAME}"
        password: "${vault:github_password}"
```

**Variable expansion:**

- `${GUAC_USERNAME}` - Guacamole username
- `${vault:key}` - Secret from Vault/OpenBao
- `${env:VAR}` - Environment variable

### Vault integration

For secure credential management:

```yaml
vault:
  enabled: true
  address: "https://vault.example.com:8200"
  roleId: ""      # AppRole auth (recommended)
  secretId: ""
  # Or use token auth
  token: ""
  mount: "secret"
  path: "guacamole/broker"
```

Store secrets in Vault:

```bash
vault kv put secret/guacamole/broker \
  github_password="xxx" \
  intranet_password="yyy"
```

## VNC container images

This project uses [docker-browser-vnc](https://github.com/MaximeWewer/docker-browser-vnc):

- **Minimal footprint** - Debian with Openbox, just enough for a browser
- **Firefox ESR or Chromium** - Enterprise-ready browsers
- **VNC server** - TigerVNC with clipboard support
- **Managed policies** - Pre-configured bookmarks, homepage, restrictions

Available images:

```
ghcr.io/maximewewer/docker-browser-vnc:2026.01.2-firefox
ghcr.io/maximewewer/docker-browser-vnc:2026.01.2-chromium
```

## Container lifecycle

```
1. User logs into Guacamole
           |
           v
2. Broker detects new user (sync every 10s)
           |
           v
3. VNC pod spawned from pool or created
           |
           v
4. Browser policies applied (bookmarks, homepage)
           |
           v
5. Guacamole connection updated with pod IP
           |
           v
6. User connects to their virtual desktop
           |
           v
7. On disconnect:
   - persist=true:  Pod kept running (idle timeout)
   - persist=false: Pod destroyed immediately
           |
           v
8. Idle timeout reached: Pod destroyed
```

### Pre-warming pool

The broker maintains a pool of ready containers:

```yaml
pool:
  enabled: true
  initContainers: 2     # Start 2 pods at broker startup
  maxContainers: 10     # Maximum total pods
  batchSize: 3          # Create up to 3 per sync cycle
```

## API reference

The broker exposes a REST API on port 5000.

### Health & status

| Endpoint              | Method | Description                           |
| --------------------- | ------ | ------------------------------------- |
| `/health`             | GET    | Health check (database, vault status) |
| `/api/config`         | GET    | Broker configuration summary          |
| `/api/secrets/status` | GET    | Secrets provider status               |

### Sessions

| Endpoint             | Method | Description             |
| -------------------- | ------ | ----------------------- |
| `/api/sessions`      | GET    | List all sessions       |
| `/api/sessions/<id>` | DELETE | Force cleanup a session |

### User operations

| Endpoint                               | Method | Description                |
| -------------------------------------- | ------ | -------------------------- |
| `/api/users/<username>/provision`      | POST   | Provision VNC connection   |
| `/api/users/<username>/groups`         | GET    | Get user's groups & config |
| `/api/users/<username>/refresh-config` | POST   | Reload group configuration |

### Sync

| Endpoint    | Method | Description              |
| ----------- | ------ | ------------------------ |
| `/api/sync` | GET    | Sync service status      |
| `/api/sync` | POST   | Trigger manual user sync |

## Troubleshooting

### Pod won't start

Check resource limits and RBAC:

```bash
# Check broker logs
kubectl logs -n guacamole -l app.kubernetes.io/name=guacamole-broker

# Check if service account has permissions
kubectl auth can-i create pods --as=system:serviceaccount:guacamole:broker-guacamole-broker -n guacamole
```

### VNC connection timeout

Increase timeout in values:

```yaml
vnc:
  timeout: 60
```

### View broker logs

```bash
kubectl logs -n guacamole -l app.kubernetes.io/name=guacamole-broker -f
```

### Force user sync

```bash
kubectl exec -n guacamole deploy/broker-guacamole-broker -- \
  curl -X POST http://localhost:5000/api/sync
```

## Project structure

```
.
├── broker/                    # Session Broker (Python/Flask)
│   ├── api/                   # REST API endpoints
│   ├── config/                # Configuration loaders
│   ├── domain/                # Core business logic
│   ├── persistence/           # Database layer
│   └── services/              # Background services
├── chart/                     # Helm chart
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/
│       ├── _helpers.tpl
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       └── rbac.yaml
└── config/                    # Example configuration files
    ├── broker.yml             # Broker settings reference
    └── profiles.yml           # User profiles reference
```

## Related projects

- [docker-browser-vnc](https://github.com/MaximeWewer/docker-browser-vnc) - Lightweight browser containers with VNC
- [guacamole-helm](https://github.com/MaximeWewer/guacamole-helm) - Helm chart for Apache Guacamole
- [Apache Guacamole](https://guacamole.apache.org/) - Clientless remote desktop gateway

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

For issues and feature requests, use [GitHub Issues](https://github.com/MaximeWewer/guacamole-webapp-gateway/issues).
