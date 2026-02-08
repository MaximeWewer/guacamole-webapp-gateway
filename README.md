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
- **API key authentication** - Secure API access with key-based auth
- **Rate limiting** - Configurable per-endpoint rate limits
- **OpenAPI documentation** - Interactive Swagger UI at `/apidocs`
- **Database connection pooling** - Efficient PostgreSQL connection management
- **Structured logging** - JSON or text log output with configurable levels
- **Prometheus metrics** - Built-in observability endpoints

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
│              STEP 2: guacamole-webapp-gateway                  │
│  (this chart - standalone deployment)                          │
├────────────────────────────────────────────────────────────────┤
│  - Session Broker (Flask API)                                  │
│  - RBAC for VNC pod management                                 │
│  - ConfigMap (broker.yml, profiles.yml)                        │
│  - Secret (Guacamole credentials, API key)                     │
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
- Helm 3.10+
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
# Add the Helm repository
helm repo add guacamole-webapp-gateway https://maximewewer.github.io/guacamole-webapp-gateway
helm repo update

# Install the broker
helm install gateway guacamole-webapp-gateway/guacamole-webapp-gateway \
  --namespace guacamole \
  --set guacamole.url=http://guacamole:8080/guacamole \
  --set guacamole.adminPassword=guacadmin \
  --set database.host=guacamole-postgresql \
  --set database.password=$PGPASSWORD \
  --set apiKey.value="my-secret-api-key"
```

Or with existing secrets:

```bash
helm install gateway guacamole-webapp-gateway/guacamole-webapp-gateway \
  --namespace guacamole \
  --set guacamole.existingSecret="guacamole-secret" \
  --set database.existingSecret="database-secret" \
  --set apiKey.existingSecret="broker-api-key-secret"
```

### 4. Verify deployment

```bash
# Check pods
kubectl get pods -n guacamole -l app.kubernetes.io/name=guacamole-webapp-gateway

# Check logs
kubectl logs -n guacamole -l app.kubernetes.io/name=guacamole-webapp-gateway

# Test health endpoint
kubectl port-forward -n guacamole svc/gateway-guacamole-webapp-gateway 5000:5000
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

# API key authentication
apiKey:
  value: ""             # Plaintext API key
  existingSecret: ""    # Or use an existing secret
  existingSecretKey: "api-key"

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

### Security

#### API key authentication

All API endpoints (except `/health`) require an `X-API-Key` header:

```bash
curl -H "X-API-Key: my-secret-api-key" http://localhost:5000/api/sessions
```

Configure via Helm values:

```yaml
apiKey:
  value: "my-secret-api-key"
  # Or reference an existing Kubernetes secret
  existingSecret: "my-secret"
  existingSecretKey: "api-key"
```

#### Rate limiting

The broker enforces per-endpoint rate limits to prevent abuse:

```yaml
security:
  rateLimiting:
    enabled: true
    defaultLimit: "200/minute"   # Read endpoints
    adminLimit: "10/minute"      # Write/admin endpoints
```

### Database connection pooling

PostgreSQL connections are managed via a connection pool:

```yaml
databasePool:
  minConnections: 2    # Minimum idle connections
  maxConnections: 8    # Maximum concurrent connections
```

### Logging

```yaml
logging:
  level: INFO          # DEBUG, INFO, WARNING, ERROR
  format: json         # json or text
```

## API documentation

Once deployed, the interactive **Swagger UI** is available at `/apidocs` on the broker service:

```bash
kubectl port-forward -n guacamole svc/gateway-guacamole-webapp-gateway 5000:5000
open http://localhost:5000/apidocs
```

The **OpenAPI JSON spec** is served at `/apispec_1.json`.

## Observability

### Prometheus metrics

The broker exposes a `/metrics` endpoint in Prometheus exposition format (exempt from rate limiting and authentication).

```bash
curl http://localhost:5000/metrics
```

#### Auto-instrumented (Flask)

Provided by `prometheus-flask-exporter`, these metrics cover every HTTP route automatically:

| Metric | Type | Description |
|--------|------|-------------|
| `flask_http_request_duration_seconds` | Histogram | Request latency by method, path and status |
| `flask_http_request_total` | Counter | Total requests by method, status |

#### Business metrics

Custom metrics updated periodically by the ConnectionMonitor:

| Metric | Type | Description |
|--------|------|-------------|
| `broker_active_containers` | Gauge | VNC containers currently running |
| `broker_pool_containers` | Gauge | Pool containers available (unclaimed) |
| `broker_active_connections` | Gauge | Active Guacamole connections |
| `broker_provisioning_duration_seconds` | Histogram | User provisioning latency (buckets: 0.5s - 60s) |
| `broker_errors_total` | Counter | Errors by endpoint label |

#### Database pool

| Metric | Type | Description |
|--------|------|-------------|
| `broker_db_pool_size` | Gauge | Total connections in the pool |
| `broker_db_pool_used` | Gauge | Connections currently checked out |

#### Circuit breaker

| Metric | Type | Description |
|--------|------|-------------|
| `broker_circuit_breaker_state` | Gauge | State per circuit: 0=closed, 1=open, 2=half-open |
| `broker_circuit_breaker_trips_total` | Counter | Times the circuit tripped to OPEN |

#### Prometheus scrape config example

```yaml
scrape_configs:
  - job_name: guacamole-webapp-gateway
    kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names: [guacamole]
    relabel_configs:
      - source_labels: [__meta_kubernetes_service_name]
        regex: gateway-guacamole-webapp-gateway
        action: keep
```

Or with a `PodMonitor` / `ServiceMonitor` (Prometheus Operator):

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: guacamole-webapp-gateway
  namespace: guacamole
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: guacamole-webapp-gateway
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
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

The broker exposes a REST API on port 5000. All endpoints except `/health` require an `X-API-Key` header.

### Health & Config

| Endpoint              | Method | Auth | Description                           |
| --------------------- | ------ | ---- | ------------------------------------- |
| `/health`             | GET    | No   | Health check (database, vault status) |
| `/api/config`         | GET    | Yes  | Broker configuration summary          |
| `/api/secrets/status` | GET    | Yes  | Secrets provider status               |

### Sessions

| Endpoint             | Method | Auth | Description             |
| -------------------- | ------ | ---- | ----------------------- |
| `/api/sessions`      | GET    | Yes  | List all sessions       |
| `/api/sessions/<id>` | DELETE | Yes  | Force cleanup a session |

### User operations

| Endpoint                               | Method | Auth | Description                    |
| -------------------------------------- | ------ | ---- | ------------------------------ |
| `/api/users/<username>/provision`      | POST   | Yes  | Provision VNC connection       |
| `/api/users/<username>/groups`         | GET    | Yes  | Get user's groups & config     |
| `/api/users/<username>/refresh-config` | POST   | Yes  | Reload group configuration     |
| `/api/users/<username>/bookmarks`      | POST   | Yes  | Update user bookmarks          |
| `/api/users/<username>/profile`        | GET    | Yes  | Get user's resolved profile    |

### Groups

| Endpoint               | Method | Auth | Description                  |
| ---------------------- | ------ | ---- | ---------------------------- |
| `/api/groups`          | GET    | Yes  | List all group configs       |
| `/api/groups/<name>`   | GET    | Yes  | Get a group configuration    |
| `/api/groups/<name>`   | PUT    | Yes  | Create/update a group config |
| `/api/groups/<name>`   | DELETE | Yes  | Delete a group configuration |

### Settings

| Endpoint        | Method | Auth | Description             |
| --------------- | ------ | ---- | ----------------------- |
| `/api/settings` | GET    | Yes  | Get broker settings     |
| `/api/settings` | PUT    | Yes  | Update broker settings  |

### Sync

| Endpoint    | Method | Auth | Description              |
| ----------- | ------ | ---- | ------------------------ |
| `/api/sync` | GET    | Yes  | Sync service status      |
| `/api/sync` | POST   | Yes  | Trigger manual user sync |

### Guacamole

| Endpoint                | Method | Auth | Description                    |
| ----------------------- | ------ | ---- | ------------------------------ |
| `/api/guacamole/groups` | GET    | Yes  | List Guacamole user groups     |

## Troubleshooting

### Pod won't start

Check resource limits and RBAC:

```bash
# Check broker logs
kubectl logs -n guacamole -l app.kubernetes.io/name=guacamole-webapp-gateway

# Check if service account has permissions
kubectl auth can-i create pods \
  --as=system:serviceaccount:guacamole:gateway-guacamole-webapp-gateway \
  -n guacamole
```

### VNC connection timeout

Increase timeout in values:

```yaml
vnc:
  timeout: 60
```

### View broker logs

```bash
kubectl logs -n guacamole -l app.kubernetes.io/name=guacamole-webapp-gateway -f
```

### Force user sync

```bash
kubectl exec -n guacamole deploy/gateway-guacamole-webapp-gateway -- \
  curl -s -H "X-API-Key: $API_KEY" -X POST http://localhost:5000/api/sync
```

## Project structure

```
.
├── broker/                    # Session Broker (Python/Flask)
│   ├── app.py                 # Application factory
│   ├── container.py           # Dependency injection container
│   ├── observability.py       # Prometheus metrics & structured logging
│   ├── resilience.py          # Circuit breaker & health checks
│   ├── api/                   # REST API
│   │   ├── routes.py          # Endpoint definitions
│   │   ├── swagger.py         # OpenAPI/Swagger configuration
│   │   ├── auth.py            # API key authentication
│   │   ├── rate_limit.py      # Rate limiting
│   │   ├── audit.py           # Audit logging
│   │   ├── validators.py      # Input validation
│   │   └── responses.py       # Standardized responses
│   ├── config/                # Configuration
│   │   ├── models.py          # Pydantic settings models
│   │   ├── loader.py          # YAML config loader
│   │   ├── secrets.py         # Vault/OpenBao integration
│   │   └── settings.py        # Environment settings
│   ├── domain/                # Core business logic
│   │   ├── session.py         # Session management
│   │   ├── guacamole.py       # Guacamole API client
│   │   ├── user_profile.py    # User profile resolution
│   │   ├── group_config.py    # Group configuration
│   │   ├── container.py       # Container operations
│   │   ├── types.py           # Domain types
│   │   └── orchestrator/      # Container orchestrators
│   │       ├── docker_orchestrator.py
│   │       └── kubernetes_orchestrator.py
│   ├── persistence/           # Database layer
│   │   ├── database.py        # Connection pooling
│   │   └── migrations.py      # Alembic migrations
│   ├── services/              # Background services
│   │   ├── user_sync.py       # User synchronization
│   │   ├── connection_monitor.py  # Connection monitoring
│   │   └── provisioning.py    # Container provisioning
│   └── migrations/            # Alembic migration scripts
│       └── versions/
├── chart/                     # Helm chart
│   ├── Chart.yaml
│   ├── values.yaml
│   ├── README.md              # Auto-generated by helm-docs
│   ├── README.md.gotmpl       # helm-docs template
│   └── templates/
│       ├── _helpers.tpl
│       ├── deployment.yaml
│       ├── service.yaml
│       ├── configmap.yaml
│       ├── secret.yaml
│       └── rbac.yaml
├── config/                    # Example configuration files
│   ├── broker.yml             # Broker settings reference
│   ├── profiles.yml           # User profiles reference
│   └── setup.yml              # Initial setup reference
├── tests/                     # Test suite
└── pyproject.toml             # Project metadata & tool config
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
