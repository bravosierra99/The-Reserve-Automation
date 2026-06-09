# Reserve Automation - Proxmox Deployment Guide

## Application Overview

**The Reserve Automation** is a FastAPI web application for managing a spirits collection (wines, whiskeys, spirits) stored in an Obsidian vault. It provides:
- PDF extraction and bottle metadata extraction using LLMs
- Obsidian note generation with templates
- Web interface for bottle management
- Event streaming for real-time updates
- Integration with local LLM (LM Studio) for AI-powered extraction

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Devices                         │
│  (Mobile, Desktop - access via http://proxmox-ip:8000)      │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                   Proxmox Server (LXC/VM)                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │         Docker Container: reserve-app                 │  │
│  │  - FastAPI web server (port 8000)                     │  │
│  │  - Runs as non-root user (appuser, UID 1000)          │  │
│  │  - Mounts: Obsidian vault, config, logs               │  │
│  └───────────────┬───────────────────────────────────────┘  │
│                  │                                           │
│  ┌───────────────▼───────────────────────────────────────┐  │
│  │        Volume: Obsidian Vault (the-reserve)           │  │
│  │  - Structured markdown notes for bottles/tastings     │  │
│  │  - Templates in 9_Templates/                           │  │
│  │  - FileClass definitions in 8_FileClass/              │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            │ HTTP calls to LM Studio API
                            │
┌───────────────────────────▼─────────────────────────────────┐
│              Windows Host (192.168.86.2)                     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │            LM Studio (port 1234)                       │ │
│  │  - Local LLM server (Qwen2.5-Coder-14B)               │ │
│  │  - Provides /v1/chat/completions API                  │ │
│  │  - Listening on 0.0.0.0:1234 (accessible from LAN)    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Critical Components

### 1. LM Studio (Separate Windows Host)
- **Location**: Windows PC at `192.168.86.2:1234`
- **Purpose**: Provides local LLM inference for bottle extraction
- **API**: OpenAI-compatible `/v1/chat/completions` endpoint
- **Model**: Qwen2.5-Coder-14B (or similar)
- **Configuration**:
  - Bound to `0.0.0.0:1234` (accessible from network)
  - Must be running before container starts
  - Container connects via environment variable `RESERVE_LM_STUDIO_URL`

### 2. Obsidian Vault (the-reserve)
- **Purpose**: Source of truth for all bottle/tasting data
- **Structure**:
  ```
  the-reserve/Cellar/
  ├── 1_Wines/{BottleName}/{BottleName}.md
  ├── 1_Whiskeys/{BottleName}/{BottleName}.md
  ├── 1_Spirits/{BottleName}/{BottleName}.md
  ├── 8_FileClass/           # Field definitions
  │   ├── Wine.md
  │   ├── Whiskey.md
  │   ├── Spirit.md
  │   └── Wine Tasting.md
  └── 9_Templates/           # Obsidian templates
      ├── Wine.md
      ├── Whiskey.md
      ├── Spirit.md
      └── Tasting Note.md
  ```
- **Integration**:
  - Automation generates markdown files in this vault
  - Templates must match Obsidian templates exactly
  - Field names must match FileClass definitions

### 3. Docker Container
- **Base Image**: `python:3.14-slim`
- **User**: Non-root `appuser` (UID 1000, GID 1000)
- **Port**: 8000 (must bind to `0.0.0.0` for external access)
- **Healthcheck**: `/api/v1/health` endpoint
- **Resource Limits**: 2GB RAM limit, 512MB reservation

## Deployment Prerequisites

### On Proxmox Host

1. **Docker and Docker Compose installed**
2. **Git installed** (to clone repository)
3. **Network access to Windows host** (`192.168.86.2`)
4. **Vault location**: Decide where to mount the Obsidian vault
   - Options:
     - NFS mount from existing location
     - Local copy on Proxmox storage
     - SMB/CIFS mount from Windows

### Repository
- **Git URL**: [Your git repository URL here]
- **Branch**: `main`
- **Key Files**:
  - `Dockerfile` - Container definition
  - `docker-compose.yml` - Service configuration
  - `.env.example` - Environment variable template
  - `src/` - Application source code
  - `config/` - Configuration files (user.yaml, system.yaml)
  - `templates/` - Jinja2 templates for Obsidian notes

## Deployment Steps

### 1. Clone Repository
```bash
cd /opt  # or your preferred location
git clone [repository-url] reserve-automation
cd reserve-automation
```

### 2. Configure Environment
```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
nano .env
```

**Required `.env` configuration:**
```bash
# Security
WEB_SECRET_KEY=<generate with: openssl rand -hex 32>

# Vault location (CRITICAL - must point to your vault)
VAULT_HOST_PATH=/path/to/the-reserve

# LM Studio connection (Windows host)
LM_STUDIO_HOST=192.168.86.2
LM_STUDIO_PORT=1234

# Ports
WEB_PORT=8000
OBSIDIAN_PORT=8080

# Optional: API keys
# ANTHROPIC_API_KEY=sk-ant-...
# LLMWHISPERER_API_KEY=...
```

### 3. Verify LM Studio Connectivity
```bash
# Test from Proxmox host
curl -s http://192.168.86.2:1234/v1/models
# Should return JSON with available models
```

### 4. Build and Start Container
```bash
# Build image
docker compose build

# Start services (Reserve app only)
docker compose up -d

# Start with Obsidian (optional)
docker compose --profile obsidian up -d
```

### 5. Verify Deployment
```bash
# Check container status
docker compose ps
# Should show: Up X seconds (healthy)

# Test health endpoint
curl http://localhost:8000/api/v1/health
# Expected: {"status":"healthy","service":"The Reserve Automation","version":"<current>"}
# (version reflects the deployed build; the unauthenticated /api/v1/version endpoint returns just version + commit_short for monitoring)

# Test from mobile/external device
curl http://<proxmox-ip>:8000/api/v1/health

# Check LM Studio connectivity from container
docker compose exec web curl -s http://192.168.86.2:1234/v1/models
# Should return JSON with models

# View logs
docker compose logs -f web
```

## Critical Configuration Files

### `config/system.yaml`
System-wide defaults (committed to git):
```yaml
vault:
  default_vault: "the-reserve"
  base_path: "/vault/Cellar"

llm:
  provider: "lmstudio"
  base_url: "http://192.168.86.2:1234/v1"
  model: "qwen/qwen2.5-coder-14b"
```

### `config/user.yaml`
User-specific overrides (committed to git):
```yaml
llm:
  model: "qwen2.5-coder-30b-a3b-instruct"
  base_url: "http://192.168.86.2:1234/v1"
```

### Environment Variables Override Order
1. `.env` file (highest priority, not in git)
2. `config/user.yaml` (committed to git)
3. `config/system.yaml` (defaults)

## Docker Compose Configuration

### Port Binding (CRITICAL for external access)
```yaml
ports:
  - "0.0.0.0:${WEB_PORT:-8000}:8000"
```
**Must use `0.0.0.0`** explicitly - important for WSL2 mirrored networking and Proxmox.

### Volume Mounts
```yaml
volumes:
  - ${VAULT_HOST_PATH}:/vault           # Obsidian vault (RW)
  - ./config:/app/config:ro              # Config files (RO)
  - reserve_temp:/tmp/reserve_uploads    # Temp uploads
  - reserve_logs:/app/logs               # Application logs
```

### Environment Variables
```yaml
environment:
  - WEB_SECRET_KEY=${WEB_SECRET_KEY}
  - RESERVE_VAULT_PATH=/vault/Cellar
  - RESERVE_LM_STUDIO_URL=http://${LM_STUDIO_HOST:-192.168.86.2}:${LM_STUDIO_PORT:-1234}/v1
  - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
  - LLMWHISPERER_API_KEY=${LLMWHISPERER_API_KEY:-}
```

## Networking Requirements

### Firewall Rules (if applicable)
```bash
# Allow incoming HTTP traffic on port 8000
iptables -A INPUT -p tcp --dport 8000 -j ACCEPT

# Or for UFW
ufw allow 8000/tcp
```

### DNS/Access
- **Local network**: `http://<proxmox-ip>:8000`
- **With reverse proxy**: `https://reserve.yourdomain.com`
  - Add Traefik/nginx labels to docker-compose.yml
  - See plan document for reverse proxy configuration

## Obsidian Integration Details

### Template Synchronization (CRITICAL)
The application templates (`templates/*.md.jinja`) **MUST** match Obsidian templates (`the-reserve/Cellar/9_Templates/*.md`) exactly:

- **Field names**: Case-sensitive, must match FileClass definitions
- **Frontmatter structure**: YAML format, must start with `---`
- **fileClass values**: Must match DataviewJS queries
  - Wine: `fileClass: "Wine"`
  - Whiskey: `fileClass: "Whiskey"`
  - Spirit: `fileClass: "Spirit"`
  - Tasting: `fileClass: "Wine Tasting"`

### File Naming Convention
```
Bottle: /vault/Cellar/1_Wines/{BottleName}/{BottleName}.md
Tasting: /vault/Cellar/1_Wines/{BottleName}/Tasting-YYYY-MM-DD-TasterName.md
```

## Common Operations

### Update Application
```bash
cd /opt/reserve-automation
git pull
docker compose down
docker compose build
docker compose up -d
```

### View Logs
```bash
# All logs
docker compose logs -f

# Just web service
docker compose logs -f web

# Last 100 lines
docker compose logs --tail 100 web
```

### Restart Service
```bash
docker compose restart web
```

### Backup
```bash
# Backup volumes
docker run --rm -v automation_reserve_logs:/data -v $(pwd):/backup alpine tar czf /backup/logs-backup.tar.gz /data

# Backup .env
cp .env .env.backup
```

## Troubleshooting

### Container won't start
```bash
# Check logs
docker compose logs web

# Common issues:
# 1. Permission denied on /app/logs
#    - Recreate volumes: docker compose down -v && docker compose up -d
# 2. Vault path not found
#    - Check VAULT_HOST_PATH in .env points to correct location
# 3. LM Studio unreachable
#    - Verify LM Studio is running and accessible from Proxmox
```

### LM Studio connectivity issues
```bash
# Test from Proxmox host
curl http://192.168.86.2:1234/v1/models

# Test from container
docker compose exec web curl http://192.168.86.2:1234/v1/models

# Common fixes:
# - Ensure LM Studio is bound to 0.0.0.0:1234
# - Check firewall on Windows host allows port 1234
# - Verify network connectivity between Proxmox and Windows
```

### Can't access from mobile/external devices
```bash
# Verify port binding
docker port reserve-app
# Should show: 8000/tcp -> 0.0.0.0:8000

# Test from Proxmox host using external IP
curl http://<proxmox-external-ip>:8000/api/v1/health

# Check firewall
iptables -L -n | grep 8000
```

### Vault not accessible
```bash
# Check mount
docker compose exec web ls -la /vault/Cellar

# Verify permissions (should be readable by UID 1000)
ls -la ${VAULT_HOST_PATH}

# Fix permissions if needed
chown -R 1000:1000 ${VAULT_HOST_PATH}
```

## Security Considerations

1. **Non-root user**: Container runs as `appuser` (UID 1000)
2. **Secret management**: `WEB_SECRET_KEY` in `.env` (not committed to git)
3. **API keys**: Optional, stored in `.env`
4. **Vault access**: Read-write access required for automation
5. **Network exposure**: Only port 8000 exposed, consider reverse proxy with SSL

## Performance Notes

- **Memory**: 2GB limit (adjust in docker-compose.yml if needed)
- **CPU**: No limit set (uses host CPU as available)
- **Storage**: Logs rotate at 10MB, keep 5 files
- **LM Studio**: Large models require significant RAM/GPU on Windows host

## Future Enhancements (from plan)

### Reverse Proxy with Traefik
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.reserve.rule=Host(`reserve.yourdomain.com`)"
  - "traefik.http.services.reserve.loadbalancer.server.port=8000"
  - "traefik.http.routers.reserve.middlewares=reserve-buffering@docker"
  - "traefik.http.middlewares.reserve-buffering.buffering.maxRequestBodyBytes=0"
  - "traefik.http.middlewares.reserve-buffering.buffering.retryExpression=IsNetworkError() && Attempts() <= 2"
```

**Note**: SSE endpoints need `proxy_buffering off` for event streaming.

## Contact/Support

- **Development**: This was developed on Windows/WSL2 with Docker Desktop
- **Tested Environments**:
  - Windows 11 + WSL2 + Docker Desktop (mirrored networking)
  - Proxmox deployment (pending)
- **Dependencies**: All in `pyproject.toml` and `uv.lock`

## Quick Reference

```bash
# Start
docker compose up -d

# Stop
docker compose down

# Logs
docker compose logs -f web

# Restart
docker compose restart web

# Shell access
docker compose exec web bash

# Health check
curl http://localhost:8000/api/v1/health

# Rebuild after code changes
docker compose down && docker compose build && docker compose up -d
```
