#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG_FILE="config/setup.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  Guacamole Session Broker - Setup${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# Check dependencies
check_dependencies() {
    local missing=()
    command -v docker &>/dev/null || missing+=("docker")
    command -v yq &>/dev/null || missing+=("yq")

    if [ ${#missing[@]} -gt 0 ]; then
        echo -e "${RED}Missing dependencies: ${missing[*]}${NC}"
        echo ""
        echo "Install yq:"
        echo "  - Linux: sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 && sudo chmod +x /usr/local/bin/yq"
        echo "  - macOS: brew install yq"
        exit 1
    fi
}

# Read config value
get_config() {
    yq eval "$1" "$CONFIG_FILE" 2>/dev/null || echo ""
}

# Set config value
set_config() {
    yq eval -i "$1 = \"$2\"" "$CONFIG_FILE"
}

# Normalize domain (remove www. prefix if present)
normalize_domain() {
    local domain="$1"
    echo "$domain" | sed 's/^www\.//'
}

# Get both domain variants (base + www)
get_domain_variants() {
    local domain="$1"
    local base_domain=$(normalize_domain "$domain")
    echo "$base_domain www.$base_domain"
}

# Interactive setup
interactive_setup() {
    echo -e "${YELLOW}[Configuration]${NC}"
    echo ""

    # Database password
    local db_pass=$(get_config '.database.password')
    if [ -z "$db_pass" ]; then
        echo -n "Database password: "
        read -s db_pass
        echo ""
        set_config '.database.password' "$db_pass"
    fi

    # Guacamole admin password
    local guac_pass=$(get_config '.guacamole.admin_password')
    if [ -z "$guac_pass" ]; then
        echo -n "Guacamole admin password: "
        read -s guac_pass
        echo ""
        set_config '.guacamole.admin_password' "$guac_pass"
    fi

    # SSL mode
    echo ""
    echo "SSL Certificate:"
    echo "  1) Self-signed (development)"
    echo "  2) Let's Encrypt (production)"
    echo -n "Choose [1/2]: "
    read ssl_choice

    case $ssl_choice in
        2)
            set_config '.ssl.mode' "letsencrypt"
            echo -n "Domain name (without www, e.g. example.com): "
            read domain
            # Normalize the domain (remove www. if present)
            domain=$(normalize_domain "$domain")
            set_config '.ssl.domain' "$domain"
            echo "  Certificate will cover both: $domain and www.$domain"
            echo -n "Email for Let's Encrypt: "
            read email
            set_config '.ssl.email' "$email"
            ;;
        *)
            set_config '.ssl.mode' "selfsigned"
            ;;
    esac

    # SSL profile
    echo ""
    echo "SSL Security Profile:"
    echo "  1) Modern (TLSv1.3 only - recommended)"
    echo "  2) Intermediate (TLSv1.2 + TLSv1.3 - for older clients)"
    echo -n "Choose [1/2]: "
    read ssl_profile_choice

    case $ssl_profile_choice in
        2)
            set_config '.ssl.profile' "intermediate"
            ;;
        *)
            set_config '.ssl.profile' "modern"
            ;;
    esac

    # URL configuration
    echo ""
    echo "URL Access Mode:"
    echo "  1) Path mode: example.com/guacamole/ (recommended)"
    echo "  2) Root mode: example.com/ (Guacamole at root)"
    echo "  3) Subdomain mode: guacamole.example.com/"
    echo -n "Choose [1/2/3]: "
    read url_mode_choice

    case $url_mode_choice in
        2)
            set_config '.nginx.url_mode' "path"
            set_config '.nginx.base_path' "/"
            echo "  Guacamole will be accessible at: https://your-domain/"
            ;;
        3)
            set_config '.nginx.url_mode' "subdomain"
            local default_sub=$(get_config '.nginx.subdomain')
            [ -z "$default_sub" ] && default_sub="guacamole"
            echo -n "Subdomain prefix [$default_sub]: "
            read subdomain
            [ -z "$subdomain" ] && subdomain="$default_sub"
            set_config '.nginx.subdomain' "$subdomain"
            echo "  Guacamole will be accessible at: https://${subdomain}.your-domain/"
            if [ "$ssl_choice" = "2" ]; then
                echo -e "  ${YELLOW}Note: Certificate will include ${subdomain}.domain in addition to domain and www.domain${NC}"
            fi
            ;;
        *)
            set_config '.nginx.url_mode' "path"
            local default_path=$(get_config '.nginx.base_path')
            [ -z "$default_path" ] && default_path="/guacamole/"
            echo -n "Base path [$default_path]: "
            read base_path
            [ -z "$base_path" ] && base_path="$default_path"
            # Ensure path starts and ends with /
            [[ "$base_path" != /* ]] && base_path="/$base_path"
            [[ "$base_path" != */ ]] && base_path="$base_path/"
            set_config '.nginx.base_path' "$base_path"
            echo "  Guacamole will be accessible at: https://your-domain${base_path}"
            ;;
    esac

    # Container versions
    echo ""
    echo "Container versions (press Enter for defaults):"

    local default_guac=$(get_config '.versions.guacamole')
    echo -n "Guacamole version [$default_guac]: "
    read guac_ver
    [ -n "$guac_ver" ] && set_config '.versions.guacamole' "$guac_ver"

    local default_pg=$(get_config '.versions.postgres')
    echo -n "PostgreSQL version [$default_pg]: "
    read pg_ver
    [ -n "$pg_ver" ] && set_config '.versions.postgres' "$pg_ver"

    local default_vnc=$(get_config '.versions.vnc')
    echo -n "VNC image [$default_vnc]: "
    read vnc_img
    [ -n "$vnc_img" ] && set_config '.versions.vnc' "$vnc_img"

    echo ""
    echo -e "${GREEN}Configuration saved to $CONFIG_FILE${NC}"
}

# Generate docker-compose.yml from config
generate_compose() {
    echo -e "${YELLOW}[Generating docker-compose.yml]${NC}"

    local guac_ver=$(get_config '.versions.guacamole')
    local guacd_ver=$(get_config '.versions.guacd')
    local pg_ver=$(get_config '.versions.postgres')
    local nginx_ver=$(get_config '.versions.nginx')
    local vnc_img=$(get_config '.versions.vnc')

    local db_host=$(get_config '.database.host')
    local db_port=$(get_config '.database.port')
    local db_name=$(get_config '.database.name')
    local db_user=$(get_config '.database.user')
    local db_pass=$(get_config '.database.password')

    local guac_user=$(get_config '.guacamole.admin_user')
    local guac_pass=$(get_config '.guacamole.admin_password')

    local guacd_log=$(get_config '.logging.guacd_level')

    local ssl_mode=$(get_config '.ssl.mode')

    local vault_enabled=$(get_config '.vault.enabled')
    local vault_addr=$(get_config '.vault.address')
    local vault_token=$(get_config '.vault.token')
    local vault_role_id=$(get_config '.vault.role_id')
    local vault_secret_id=$(get_config '.vault.secret_id')
    local vault_mount=$(get_config '.vault.mount')
    local vault_path=$(get_config '.vault.path')

    # Get Docker socket GID for container access
    local docker_gid=$(getent group docker | cut -d: -f3)
    if [ -z "$docker_gid" ]; then
        docker_gid=999  # Default fallback
        echo -e "${YELLOW}Warning: Could not detect docker group GID, using default 999${NC}"
    fi

    cat > docker-compose.yml << EOF
services:
  postgres:
    image: postgres:${pg_ver}
    container_name: guacamole-db
    environment:
      POSTGRES_DB: ${db_name}
      POSTGRES_USER: ${db_user}
      POSTGRES_PASSWORD: ${db_pass}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./initdb:/docker-entrypoint-initdb.d:ro
    networks:
      - guacamole-internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${db_user} -d ${db_name}"]
      interval: 10s
      timeout: 5s
      retries: 5
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    restart: unless-stopped

  guacd:
    image: guacamole/guacd:${guacd_ver}
    container_name: guacd
    user: root
    entrypoint: entrypoint: ["/bin/sh", "-c", "chmod 777 /recordings && (while true; do chmod -R a+rX /recordings 2>/dev/null; sleep 5; done) & exec /opt/guacamole/sbin/guacd -b 0.0.0.0 -L $$GUACD_LOG_LEVEL -f"]
    environment:
      GUACD_LOG_LEVEL: ${guacd_log}
    volumes:
      - guacd_recordings:/recordings
    networks:
      - guacamole-internal
      - vnc-network
    cap_add:
      - NET_ADMIN
    healthcheck:
      test: ["CMD-SHELL", "nc -z localhost 4822 || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    restart: unless-stopped

  guacamole:
    image: guacamole/guacamole:${guac_ver}
    container_name: guacamole
    environment:
      GUACD_HOSTNAME: guacd
      GUACD_PORT: 4822
      POSTGRESQL_HOSTNAME: postgres
      POSTGRESQL_PORT: ${db_port}
      POSTGRESQL_DATABASE: ${db_name}
      POSTGRESQL_USER: ${db_user}
      POSTGRESQL_PASSWORD: ${db_pass}
    networks:
      - guacamole-internal
      - guacamole-frontend
    depends_on:
      postgres:
        condition: service_healthy
      guacd:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/guacamole/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    restart: unless-stopped

  session-broker:
    build:
      context: ./broker
      args:
        DOCKER_GID: ${docker_gid}
    container_name: session-broker
    environment:
      # Guacamole API connection
      GUACAMOLE_URL: http://guacamole:8080/guacamole
      GUACAMOLE_ADMIN_USER: ${guac_user}
      GUACAMOLE_ADMIN_PASSWORD: ${guac_pass}
      # Database connection
      DATABASE_HOST: postgres
      DATABASE_PORT: ${db_port}
      DATABASE_NAME: ${db_name}
      DATABASE_USER: ${db_user}
      DATABASE_PASSWORD: ${db_pass}
      # Docker settings
      GUACD_HOSTNAME: guacd
      USER_PROFILES_VOLUME: guacamole_user_profiles
EOF

    # Add Vault config if enabled
    if [ "$vault_enabled" = "true" ]; then
        cat >> docker-compose.yml << EOF
      VAULT_ADDR: ${vault_addr}
      VAULT_TOKEN: ${vault_token}
      VAULT_ROLE_ID: ${vault_role_id}
      VAULT_SECRET_ID: ${vault_secret_id}
      VAULT_MOUNT: ${vault_mount}
      VAULT_PATH: ${vault_path}
EOF
    fi

    cat >> docker-compose.yml << EOF
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - user_profiles:/data/users
      - ./config:/data/config:ro
    networks:
      - guacamole-internal
      - vnc-network
    cap_add:
      - NET_ADMIN
    depends_on:
      postgres:
        condition: service_healthy
      guacamole:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    restart: unless-stopped

  nginx:
    image: nginx:${nginx_ver}
    container_name: nginx
    volumes:
      - ./nginx/conf/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/conf/guacamole.conf:/etc/nginx/conf.d/default.conf:ro
EOF

    if [ "$ssl_mode" = "letsencrypt" ]; then
        cat >> docker-compose.yml << EOF
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
    command: "/bin/sh -c 'while :; do sleep 6h & wait \$\${!}; nginx -s reload; done & nginx -g \"daemon off;\"'"
EOF
    else
        cat >> docker-compose.yml << EOF
      - ./nginx/ssl:/etc/nginx/ssl:ro
EOF
    fi

    cat >> docker-compose.yml << EOF
    ports:
      - "80:80"
      - "443:443"
    networks:
      - guacamole-frontend
      - guacamole-internal
    depends_on:
      guacamole:
        condition: service_healthy
      session-broker:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
    restart: unless-stopped
EOF

    # Add certbot if Let's Encrypt
    if [ "$ssl_mode" = "letsencrypt" ]; then
        cat >> docker-compose.yml << EOF

  certbot:
    image: certbot/certbot
    container_name: certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait \$\${!}; done;'"
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "2"
    restart: unless-stopped
EOF
    fi

    cat >> docker-compose.yml << EOF

networks:
  guacamole-internal:
    driver: bridge
    internal: true
  guacamole-frontend:
    driver: bridge
  vnc-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16

volumes:
  postgres_data:
  user_profiles:
  guacd_recordings:
EOF

    echo "  docker-compose.yml generated"
}

# Generate SSL certificate (self-signed)
generate_selfsigned_ssl() {
    echo -e "${YELLOW}[Generating self-signed SSL certificate]${NC}"
    mkdir -p nginx/ssl

    if [ ! -f nginx/ssl/nginx.crt ]; then
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
            -keyout nginx/ssl/nginx.key \
            -out nginx/ssl/nginx.crt \
            -subj "/C=FR/ST=France/L=Strasbourg/O=Development/CN=localhost" 2>/dev/null
        chmod 644 nginx/ssl/nginx.crt
        chmod 600 nginx/ssl/nginx.key
        echo "  Certificate generated"
    else
        echo "  Certificate already exists"
    fi
}

# Setup Let's Encrypt
setup_letsencrypt() {
    echo -e "${YELLOW}[Setting up Let's Encrypt]${NC}"

    local domain=$(get_config '.ssl.domain')
    local email=$(get_config '.ssl.email')
    local base_domain=$(normalize_domain "$domain")
    local url_mode=$(get_config '.nginx.url_mode')
    local subdomain=$(get_config '.nginx.subdomain')

    mkdir -p certbot/conf certbot/www

    # Build domain list based on url_mode
    if [ "$url_mode" = "subdomain" ] && [ -n "$subdomain" ]; then
        # Subdomain mode: only subdomain.domain and www.subdomain.domain
        local domain_list="-d ${subdomain}.\$BASE_DOMAIN -d www.${subdomain}.\$BASE_DOMAIN"
        local domain_echo="  - ${subdomain}.\$BASE_DOMAIN\\n  - www.${subdomain}.\$BASE_DOMAIN"
        local cert_dir="${subdomain}.${base_domain}"
    else
        # Path mode: domain and www.domain
        local domain_list="-d \$BASE_DOMAIN -d www.\$BASE_DOMAIN"
        local domain_echo="  - \$BASE_DOMAIN\\n  - www.\$BASE_DOMAIN"
        local cert_dir="${base_domain}"
    fi

    # Create init script for Let's Encrypt
    cat > init-letsencrypt.sh << EOF
#!/bin/bash
set -e

BASE_DOMAIN="${base_domain}"
EMAIL="${email}"

echo "Requesting certificate for:"
echo -e "${domain_echo}"
echo ""

# Start nginx for ACME challenge
docker compose up -d nginx

# Wait for nginx to be ready
sleep 5

# Get certificate for all domains
docker compose run --rm certbot certonly --webroot \\
    --webroot-path=/var/www/certbot \\
    --email \$EMAIL \\
    --agree-tos \\
    --no-eff-email \\
    ${domain_list}

# Restart nginx with SSL
docker compose restart nginx

echo ""
echo "Certificate obtained successfully!"
EOF
    chmod +x init-letsencrypt.sh

    echo "  Run ./init-letsencrypt.sh after 'docker compose up -d' to obtain certificate"
    if [ "$url_mode" = "subdomain" ] && [ -n "$subdomain" ]; then
        echo "  Certificate will cover: ${subdomain}.$base_domain, www.${subdomain}.$base_domain"
    else
        echo "  Certificate will cover: $base_domain, www.$base_domain"
    fi
}

# Generate nginx config based on SSL mode
generate_nginx_config() {
    echo -e "${YELLOW}[Generating nginx configuration]${NC}"

    local ssl_mode=$(get_config '.ssl.mode')
    local ssl_profile=$(get_config '.ssl.profile')
    local domain=$(get_config '.ssl.domain')
    local resolver=$(get_config '.ssl.resolver')
    local url_mode=$(get_config '.nginx.url_mode')
    local base_path=$(get_config '.nginx.base_path')
    local subdomain=$(get_config '.nginx.subdomain')

    # Defaults
    [ -z "$ssl_profile" ] && ssl_profile="modern"
    [ -z "$resolver" ] && resolver="1.1.1.1 8.8.8.8"
    [ -z "$url_mode" ] && url_mode="path"
    [ -z "$base_path" ] && base_path="/guacamole/"
    [ -z "$subdomain" ] && subdomain="guacamole"

    mkdir -p nginx/conf

    # Main nginx.conf with Mozilla modern SSL config
    cat > nginx/conf/nginx.conf << EOF
# Mozilla Guideline - Modern Configuration
# https://ssl-config.mozilla.org/

user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                    '\$status \$body_bytes_sent "\$http_referer" '
                    '"\$http_user_agent" "\$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;

    # Security
    server_tokens off;

    # Performance
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;

    # Compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml;

    # SSL - Modern configuration (TLSv1.3 only)
EOF

    if [ "$ssl_profile" = "modern" ]; then
        cat >> nginx/conf/nginx.conf << 'EOF'
    ssl_protocols TLSv1.3;
    ssl_ecdh_curve X25519:prime256v1:secp384r1;
EOF
    else
        # Intermediate configuration (TLSv1.2 + TLSv1.3)
        cat >> nginx/conf/nginx.conf << 'EOF'
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
EOF
    fi

    cat >> nginx/conf/nginx.conf << EOF
    ssl_prefer_server_ciphers off;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver ${resolver} valid=300s;
    resolver_timeout 5s;

    # WebSocket upgrade map
    map \$http_upgrade \$connection_upgrade {
        default upgrade;
        '' close;
    }

    include /etc/nginx/conf.d/*.conf;
}
EOF

    # SSL configuration
    if [ "$ssl_mode" = "letsencrypt" ]; then
        local base_domain=$(normalize_domain "$domain")
        if [ "$url_mode" = "subdomain" ]; then
            # Subdomain mode: cert is for subdomain.domain
            local cert_domain="${subdomain}.${base_domain}"
        else
            # Path mode: cert is for base domain
            local cert_domain="${base_domain}"
        fi
        local ssl_cert="/etc/letsencrypt/live/${cert_domain}/fullchain.pem"
        local ssl_key="/etc/letsencrypt/live/${cert_domain}/privkey.pem"
        local ssl_trusted="/etc/letsencrypt/live/${cert_domain}/chain.pem"
    else
        local base_domain=""
        local cert_domain=""
        local ssl_cert="/etc/nginx/ssl/nginx.crt"
        local ssl_key="/etc/nginx/ssl/nginx.key"
        local ssl_trusted=""
    fi

    # Start guacamole.conf with upstreams
    cat > nginx/conf/guacamole.conf << 'EOF'
# Upstreams
upstream guacamole {
    server guacamole:8080;
    keepalive 32;
}

upstream broker {
    server session-broker:5000;
    keepalive 8;
}
EOF

    # HTTP server block
    if [ "$ssl_mode" = "letsencrypt" ]; then
        if [ "$url_mode" = "subdomain" ]; then
            # Subdomain mode: only handle subdomain and www.subdomain
            local http_server_name="${subdomain}.${base_domain} www.${subdomain}.${base_domain}"
        else
            # Path mode: handle domain and www.domain
            local http_server_name="${base_domain} www.${base_domain}"
        fi
    else
        local http_server_name="_"
    fi

    cat >> nginx/conf/guacamole.conf << EOF

# HTTP - Redirect to HTTPS
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${http_server_name};

    # Let's Encrypt ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    # Health check (no redirect)
    location /health {
        return 200 'OK';
        add_header Content-Type text/plain;
    }

    # Redirect all HTTP to HTTPS
    location / {
        return 301 https://\$host\$request_uri;
    }
}
EOF

    # www redirect (Let's Encrypt only)
    if [ "$ssl_mode" = "letsencrypt" ]; then
        if [ "$url_mode" = "subdomain" ]; then
            # Subdomain mode: redirect www.subdomain.domain to subdomain.domain
            cat >> nginx/conf/guacamole.conf << EOF

# Redirect www.${subdomain} to ${subdomain} (canonical URL)
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name www.${subdomain}.${base_domain};

    ssl_certificate ${ssl_cert};
    ssl_certificate_key ${ssl_key};
    ssl_trusted_certificate ${ssl_trusted};

    return 301 https://${subdomain}.${base_domain}\$request_uri;
}
EOF
        else
            # Path mode: redirect www.domain to domain
            cat >> nginx/conf/guacamole.conf << EOF

# Redirect www to non-www (canonical URL)
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name www.${base_domain};

    ssl_certificate ${ssl_cert};
    ssl_certificate_key ${ssl_key};
    ssl_trusted_certificate ${ssl_trusted};

    return 301 https://${base_domain}\$request_uri;
}
EOF
        fi
    fi

    # Main HTTPS server block
    cat >> nginx/conf/guacamole.conf << EOF

# HTTPS - Main server
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
EOF

    # Set server_name based on mode
    if [ "$ssl_mode" = "letsencrypt" ]; then
        if [ "$url_mode" = "subdomain" ]; then
            echo "    server_name ${subdomain}.${base_domain};" >> nginx/conf/guacamole.conf
        else
            echo "    server_name ${base_domain};" >> nginx/conf/guacamole.conf
        fi
    else
        echo "    server_name _;" >> nginx/conf/guacamole.conf
    fi

    cat >> nginx/conf/guacamole.conf << EOF

    # SSL Certificates
    ssl_certificate ${ssl_cert};
    ssl_certificate_key ${ssl_key};
EOF

    if [ -n "$ssl_trusted" ]; then
        cat >> nginx/conf/guacamole.conf << EOF
    ssl_trusted_certificate ${ssl_trusted};
EOF
    fi

    cat >> nginx/conf/guacamole.conf << 'EOF'

    # Security Headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
EOF

    # Generate location blocks based on url_mode and base_path
    if [ "$url_mode" = "subdomain" ] || [ "$base_path" = "/" ]; then
        # Root access: Guacamole at /
        cat >> nginx/conf/guacamole.conf << 'EOF'

    # Guacamole Application (root)
    location / {
        proxy_pass http://guacamole/guacamole/;
        proxy_buffering off;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;

        proxy_cookie_path /guacamole/ /;
    }

    # Guacamole WebSocket tunnel
    location /websocket-tunnel {
        proxy_pass http://guacamole/guacamole/websocket-tunnel;
        proxy_buffering off;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
    }

    # Session Broker API (uses /broker/ to avoid conflict with Guacamole's /api/)
    location /broker/ {
        proxy_pass http://broker/api/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 30;
        proxy_send_timeout 30;
        proxy_read_timeout 30;
    }

    # Health check
    location /health {
        return 200 'OK';
        add_header Content-Type text/plain;
    }
}
EOF
    else
        # Path mode: Guacamole at custom path (e.g., /guacamole/)
        cat >> nginx/conf/guacamole.conf << EOF

    # Guacamole Application
    location ${base_path} {
        proxy_pass http://guacamole/guacamole/;
        proxy_buffering off;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;

        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;

        proxy_cookie_path /guacamole/ ${base_path};
    }

    # Guacamole WebSocket tunnel
    location ${base_path}websocket-tunnel {
        proxy_pass http://guacamole/guacamole/websocket-tunnel;
        proxy_buffering off;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
    }

    # Session Broker API (uses /broker/ to avoid conflict with Guacamole's /api/)
    location /broker/ {
        proxy_pass http://broker/api/;
        proxy_http_version 1.1;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_connect_timeout 30;
        proxy_send_timeout 30;
        proxy_read_timeout 30;
    }

    # Health check
    location /health {
        return 200 'OK';
        add_header Content-Type text/plain;
    }

    # Root redirect to Guacamole
    location = / {
        return 302 ${base_path};
    }
}
EOF
    fi

    # Log the configuration
    if [ "$url_mode" = "subdomain" ]; then
        echo "  Nginx configuration generated (subdomain: ${subdomain}.*, SSL: $ssl_profile)"
    else
        echo "  Nginx configuration generated (path: ${base_path}, SSL: $ssl_profile)"
    fi
}

# Generate PostgreSQL schema
generate_schema() {
    echo -e "${YELLOW}[Generating PostgreSQL schema]${NC}"
    mkdir -p initdb
    chmod +x initdb

    if [ ! -f initdb/001-schema.sql ]; then
        local guac_ver=$(get_config '.versions.guacamole')
        docker run --rm "guacamole/guacamole:${guac_ver}" /opt/guacamole/bin/initdb.sh --postgresql > initdb/001-schema.sql
        echo "  Schema generated"
    else
        echo "  Schema already exists"
    fi
}

# Pull Docker images
pull_images() {
    echo -e "${YELLOW}[Pulling Docker images]${NC}"

    local guac_ver=$(get_config '.versions.guacamole')
    local guacd_ver=$(get_config '.versions.guacd')
    local pg_ver=$(get_config '.versions.postgres')
    local nginx_ver=$(get_config '.versions.nginx')
    # VNC image is defined in broker.yml, not setup.yml
    local vnc_img=$(yq eval '.containers.image' config/broker.yml 2>/dev/null)

    docker pull "guacamole/guacamole:${guac_ver}"
    docker pull "guacamole/guacd:${guacd_ver}"
    docker pull "postgres:${pg_ver}"
    docker pull "nginx:${nginx_ver}"
    if [ -n "$vnc_img" ] && [ "$vnc_img" != "null" ]; then
        docker pull "${vnc_img}"
    fi
}

# Create directories
create_directories() {
    echo -e "${YELLOW}[Creating directories]${NC}"
    mkdir -p broker 2>/dev/null || true
    mkdir -p initdb 2>/dev/null || true
    mkdir -p nginx/conf 2>/dev/null || true
}

# Main
main() {
    check_dependencies

    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}Configuration file not found: $CONFIG_FILE${NC}"
        exit 1
    fi

    # Check if passwords are set
    local db_pass=$(get_config '.database.password')
    local guac_pass=$(get_config '.guacamole.admin_password')

    if [ -z "$db_pass" ] || [ -z "$guac_pass" ]; then
        interactive_setup
    fi

    create_directories
    generate_schema
    generate_compose
    generate_nginx_config

    local ssl_mode=$(get_config '.ssl.mode')
    if [ "$ssl_mode" = "letsencrypt" ]; then
        setup_letsencrypt
    else
        generate_selfsigned_ssl
    fi

    echo ""
    echo -n "Pull Docker images now? [y/N]: "
    read pull_choice
    if [ "$pull_choice" = "y" ] || [ "$pull_choice" = "Y" ]; then
        pull_images
    fi

    echo ""
    echo -e "${GREEN}============================================================${NC}"
    echo -e "${GREEN}  Setup Complete!${NC}"
    echo -e "${GREEN}============================================================${NC}"
    echo ""
    echo "Start services:"
    echo "  docker compose up -d"
    echo ""
    if [ "$ssl_mode" = "letsencrypt" ]; then
        echo "Then run:"
        echo "  ./init-letsencrypt.sh"
        echo ""
    fi
    echo "Configure user profiles:"
    echo "  Edit config/profiles.yml (auto-reloaded every X second - Define in broker.yml)"
}

main "$@"
