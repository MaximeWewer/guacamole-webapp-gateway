# guacamole-webapp-gateway


![Version: 1.0.0](https://img.shields.io/badge/Version-1.0.0-informational?style=flat-square) ![Type: application](https://img.shields.io/badge/Type-application-informational?style=flat-square) ![AppVersion: 1.0.0](https://img.shields.io/badge/AppVersion-1.0.0-informational?style=flat-square) 

Session Broker for Apache Guacamole - manages VNC container lifecycle

## Prerequisites

- Kubernetes 1.25+
- Helm 3.10+
- A running [Apache Guacamole](https://guacamole.apache.org/) instance (see [guacamole-helm](https://github.com/MaximeWewer/guacamole-helm))
- A PostgreSQL database accessible from the cluster

## Installation

```bash
helm repo add guacamole-webapp-gateway https://maximewewer.github.io/guacamole-webapp-gateway
helm install gateway guacamole-webapp-gateway/guacamole-webapp-gateway \
  --set guacamole.adminPassword="changeme" \
  --set database.password="changeme" \
  --set apiKey.value="my-secret-api-key"
```

Or with an existing secret:

```bash
helm install gateway guacamole-webapp-gateway/guacamole-webapp-gateway \
  --set guacamole.existingSecret="guacamole-secret" \
  --set database.existingSecret="database-secret" \
  --set apiKey.existingSecret="broker-api-key-secret"
```

## Architecture

```
                    +-------------------+
                    |   Guacamole Web   |
                    +--------+----------+
                             |
                    +--------v----------+
                    |  Session Broker   |  <-- this chart
                    |  (Flask API)      |
                    +--+------+------+--+
                       |      |      |
              +--------+  +---+----+ +---------+
              |           |        |           |
        +-----v-----+ +---v----+ +-v--------+  |
        | PostgreSQL | | guacd | | Guac API |  |
        +------------+ +-------+ +----------+  |
                                               |
                    +--------------------------v----+
                    |  VNC Pods (managed by broker) |
                    +-------------------------------+
```

The broker manages the full lifecycle of VNC containers:

1. **User Sync** -- Periodically syncs Guacamole users and provisions connections
2. **Container Pool** -- Pre-warms VNC containers for instant session start
3. **Session Management** -- Spawns/destroys containers on connect/disconnect
4. **Group Config** -- Per-group browser profiles (bookmarks, homepage, autofill)

## API Documentation

Once deployed, the interactive Swagger UI is available at `/apidocs` on the broker service.
The OpenAPI JSON spec is served at `/apispec_1.json`.

## Vault Integration

The broker supports [HashiCorp Vault](https://www.vaultproject.io/) or [OpenBao](https://openbao.org/) for secret management.
This allows using `${vault:key}` variables in user profile autofill credentials.

```yaml
vault:
  enabled: true
  address: "https://vault.example.com"
  roleId: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  secretId: "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"

profiles:
  developers:
    autofill:
      - url: "https://gitlab.example.com/users/sign_in"
        username: "${GUAC_USERNAME}"
        password: "${vault:gitlab_password}"
```

## User Profiles

Profiles define per-group browser configuration (bookmarks, homepage, autofill).
They are defined inline in `values.yaml` under the `profiles` key, or via an external ConfigMap.

Supported variable expansion:

| Variable | Description |
|----------|-------------|
| `${GUAC_USERNAME}` | Guacamole username of the connected user |
| `${vault:key}` | Secret from Vault (requires `vault.enabled: true`) |
| `${env:VAR}` | Environment variable from the broker container |

## Values

### Guacamole Connection

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| guacamole | object | `{"adminPassword":"","adminUser":"guacadmin","existingSecret":"","existingSecretKey":"password","url":"http://guacamole:8080/guacamole"}` | --------------------------------------------------------------------------- |
| guacamole.url | string | `"http://guacamole:8080/guacamole"` | URL of the Guacamole service (K8s service name or external URL) |
| guacamole.adminUser | string | `"guacadmin"` | Admin username |
| guacamole.adminPassword | string | `""` | Admin password (required if existingSecret not set) |
| guacamole.existingSecret | string | `""` | Use an existing secret for the admin password |
| guacamole.existingSecretKey | string | `"password"` | Key in the existing secret containing the password |

### Database

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| database | object | `{"existingSecret":"","existingSecretKey":"password","host":"guacamole-postgresql","name":"guacamole","password":"","port":5432,"user":"guacamole"}` | --------------------------------------------------------------------------- |
| database.host | string | `"guacamole-postgresql"` | PostgreSQL hostname (K8s service name or external host) |
| database.port | int | `5432` | PostgreSQL port |
| database.name | string | `"guacamole"` | Database name for the broker (can be same as Guacamole) |
| database.user | string | `"guacamole"` | Database user |
| database.password | string | `""` | Password (required if existingSecret not set) |
| database.existingSecret | string | `""` | Use an existing secret for the database password |
| database.existingSecretKey | string | `"password"` | Key in the existing secret containing the password |
| databasePool | object | `{"maxConnections":8,"minConnections":2}` | --------------------------------------------------------------------------- |
| databasePool.minConnections | int | `2` | Minimum connections in the pool |
| databasePool.maxConnections | int | `8` | Maximum connections in the pool |

### Vault / OpenBao

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| vault | object | `{"address":"","enabled":false,"existingSecret":"","mount":"secret","path":"guacamole/broker","roleId":"","secretId":"","token":""}` | --------------------------------------------------------------------------- Allows using ${vault:key} in autofill credentials |
| vault.enabled | bool | `false` | Enable Vault/OpenBao secret provider |
| vault.address | string | `""` | Vault server address |
| vault.token | string | `""` | Auth by token (for development) |
| vault.roleId | string | `""` | AppRole role ID (recommended for production) |
| vault.secretId | string | `""` | AppRole secret ID |
| vault.existingSecret | string | `""` | Existing secret containing Vault credentials Keys: VAULT_TOKEN or VAULT_ROLE_ID + VAULT_SECRET_ID |
| vault.mount | string | `"secret"` | Vault mount path |
| vault.path | string | `"guacamole/broker"` | Path to secrets in Vault |

### Broker Deployment

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| image | object | `{"pullPolicy":"IfNotPresent","repository":"ghcr.io/maximewewer/guacamole-webapp-gateway","tag":"latest"}` | --------------------------------------------------------------------------- |
| image.repository | string | `"ghcr.io/maximewewer/guacamole-webapp-gateway"` | Container image repository |
| image.tag | string | `"latest"` | Container image tag |
| image.pullPolicy | string | `"IfNotPresent"` | Image pull policy |
| imagePullSecrets | list | `[]` | Image pull secrets for the broker pod |
| replicaCount | int | `1` | Number of broker replicas |
| resources | object | `{"limits":{"cpu":"500m","memory":"512Mi"},"requests":{"cpu":"100m","memory":"128Mi"}}` | Resource requests and limits for the broker pod |
| nodeSelector | object | `{}` | Node selector for broker pod scheduling |
| tolerations | list | `[]` | Tolerations for broker pod scheduling |
| affinity | object | `{}` | Affinity rules for broker pod scheduling |
| podAnnotations | object | `{}` | Additional annotations for the broker pod |
| podSecurityContext | object | `{}` | Pod-level security context |
| securityContext | object | `{}` | Container-level security context |

### API Key Authentication

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| apiKey | object | `{"existingSecret":"","existingSecretKey":"api-key","value":""}` | API key for authenticating with the broker API |
| apiKey.value | string | `""` | Plaintext API key value (required if existingSecret not set) |
| apiKey.existingSecret | string | `""` | Use an existing secret containing the API key |
| apiKey.existingSecretKey | string | `"api-key"` | Key in the existing secret containing the API key |

### Service

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| service | object | `{"port":5000,"type":"ClusterIP"}` | Service configuration |
| service.type | string | `"ClusterIP"` | Kubernetes service type |
| service.port | int | `5000` | Service port |

### Container Orchestrator (Kubernetes)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| orchestrator | object | `{"imagePullPolicy":"IfNotPresent","imagePullSecrets":[],"labels":{"app":"vnc-session","managed-by":"guacamole-webapp-gateway"},"namespace":"","nodeSelector":{},"securityContext":{"runAsNonRoot":false,"runAsUser":1000},"tolerations":[]}` | --------------------------------------------------------------------------- |
| orchestrator.namespace | string | Release namespace | Namespace for VNC pods |
| orchestrator.labels | object | `{"app":"vnc-session","managed-by":"guacamole-webapp-gateway"}` | Labels applied to all VNC pods |
| orchestrator.imagePullPolicy | string | `"IfNotPresent"` | Image pull policy for VNC pods: Always, IfNotPresent, Never |
| orchestrator.imagePullSecrets | list | `[]` | Image pull secrets for VNC pods |
| orchestrator.nodeSelector | object | `{}` | Node selector for VNC pod scheduling |
| orchestrator.tolerations | list | `[]` | Tolerations for VNC pod scheduling |
| orchestrator.securityContext | object | `{"runAsNonRoot":false,"runAsUser":1000}` | Security context for VNC pods |

### VNC Containers

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| vnc | object | `{"connectionName":"Virtual Desktop","image":{"repository":"ghcr.io/maximewewer/docker-browser-vnc","tag":"2026.01.2-chromium"},"resources":{"limits":{"cpu":"1000m","memory":"2Gi"},"requests":{"cpu":"250m","memory":"512Mi"}},"timeout":30}` | --------------------------------------------------------------------------- |
| vnc.image.repository | string | `"ghcr.io/maximewewer/docker-browser-vnc"` | VNC container image repository |
| vnc.image.tag | string | `"2026.01.2-chromium"` | VNC container image tag |
| vnc.connectionName | string | `"Virtual Desktop"` | Connection name displayed in Guacamole |
| vnc.timeout | int | `30` | Timeout in seconds to wait for VNC to be ready |
| vnc.resources | object | `{"limits":{"cpu":"1000m","memory":"2Gi"},"requests":{"cpu":"250m","memory":"512Mi"}}` | Resource requests and limits for VNC pods |

### User Synchronization

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| sync | object | `{"ignoredUsers":["guacadmin"],"interval":10,"syncConfigOnRestart":true}` | --------------------------------------------------------------------------- |
| sync.interval | int | `10` | Sync interval in seconds |
| sync.ignoredUsers | list | `["guacadmin"]` | Users to ignore during sync (system accounts) |
| sync.syncConfigOnRestart | bool | `true` | Force update existing connections on broker restart |

### Container Pool

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| pool | object | `{"batchSize":3,"enabled":true,"initContainers":2,"maxContainers":10,"resources":{"maxMemoryPercent":0.75,"maxTotalMemoryGb":16,"minFreeMemoryGb":2}}` | --------------------------------------------------------------------------- |
| pool.enabled | bool | `true` | Enable container pre-warming |
| pool.initContainers | int | `2` | Containers to start at broker startup |
| pool.maxContainers | int | `10` | Maximum number of containers |
| pool.batchSize | int | `3` | Containers to start per sync cycle |
| pool.resources | object | `{"maxMemoryPercent":0.75,"maxTotalMemoryGb":16,"minFreeMemoryGb":2}` | Resource limits for pool management |
| pool.resources.minFreeMemoryGb | float | `2` | Minimum free RAM required to start a new container (GB) |
| pool.resources.maxTotalMemoryGb | float | `16` | Maximum total RAM for all VNC containers (GB), 0 = no limit |
| pool.resources.maxMemoryPercent | float | `0.75` | Maximum percentage of total RAM, 0 = no limit |

### Container Lifecycle

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| lifecycle | object | `{"forceKillOnLowResources":true,"idleTimeoutMinutes":3,"persistAfterDisconnect":true}` | --------------------------------------------------------------------------- |
| lifecycle.persistAfterDisconnect | bool | `true` | Keep containers running after user disconnects |
| lifecycle.idleTimeoutMinutes | int | `3` | Idle timeout in minutes (after disconnect) |
| lifecycle.forceKillOnLowResources | bool | `true` | Force kill oldest inactive containers when resources are low |

### Guacamole Interface

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| guacamoleSettings | object | `{"forceHomePage":true,"homeConnectionName":"Home","recording":{"autoCreatePath":true,"enabled":true,"includeKeys":false,"name":"","path":"${HISTORY_PATH}/${HISTORY_UUID}"}}` | --------------------------------------------------------------------------- |
| guacamoleSettings.forceHomePage | bool | `true` | Force display of home page instead of auto-connecting |
| guacamoleSettings.homeConnectionName | string | `"Home"` | Name of the placeholder home connection |
| guacamoleSettings.recording | object | `{"autoCreatePath":true,"enabled":true,"includeKeys":false,"name":"","path":"${HISTORY_PATH}/${HISTORY_UUID}"}` | Session recording configuration |
| guacamoleSettings.recording.enabled | bool | `true` | Enable session recording |
| guacamoleSettings.recording.path | string | `"${HISTORY_PATH}/${HISTORY_UUID}"` | Path inside guacd container (use Guacamole variables) |
| guacamoleSettings.recording.name | string | `""` | Recording filename pattern |
| guacamoleSettings.recording.includeKeys | bool | `false` | Include keyboard input in recordings |
| guacamoleSettings.recording.autoCreatePath | bool | `true` | Auto-create recording path |

### Security & Rate Limiting

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| security | object | `{"rateLimiting":{"adminLimit":"10/minute","defaultLimit":"200/minute","enabled":true}}` | --------------------------------------------------------------------------- |
| security.rateLimiting.enabled | bool | `true` | Enable rate limiting |
| security.rateLimiting.defaultLimit | string | `"200/minute"` | Default limit for read endpoints |
| security.rateLimiting.adminLimit | string | `"10/minute"` | Stricter limit for write/admin endpoints |

### Logging

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| logging | object | `{"format":"json","level":"INFO"}` | --------------------------------------------------------------------------- |
| logging.level | string | `"INFO"` | Log level: DEBUG, INFO, WARNING, ERROR |
| logging.format | string | `"json"` | Log format: json or text |

### User Profiles

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| profiles | object | `{"default":{"bookmarks":[{"name":"Google","url":"https://www.google.com"},{"name":"DuckDuckGo","url":"https://duckduckgo.com"}],"description":"Default profile for all users","homepage":"https://www.google.com","priority":0}}` | Browser profiles per Guacamole user group |
| externalProfilesConfigMap | string | `""` | Use an external ConfigMap for profiles instead of inline. If set, the profiles section above is ignored. |

### RBAC

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| serviceAccount | object | `{"annotations":{},"create":true,"name":""}` | --------------------------------------------------------------------------- |
| serviceAccount.create | bool | `true` | Create a service account for the broker |
| serviceAccount.annotations | object | `{}` | Annotations for the service account |
| serviceAccount.name | string | Release fullname | Name override |
| rbac.create | bool | `true` | Create Role and RoleBinding for pod management |
