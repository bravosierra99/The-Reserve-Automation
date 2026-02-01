# Claude Instance Handoff - Reserve Automation Proxmox Deployment

## Context for New Claude Instance

You are helping deploy **The Reserve Automation** application to a Proxmox server. This is a production deployment of an existing, working application currently running on Windows/WSL2.

## What This Application Does

FastAPI web app for managing a spirits collection stored in an Obsidian vault. Key features:
- PDF extraction → LLM analysis → Structured bottle metadata → Obsidian markdown notes
- Web UI for bottle/tasting management
- Real-time event streaming (SSE)
- Integration with user's local LLM server (LM Studio on separate Windows host)

## Critical Architecture Points

### 1. **Multi-Host Setup**
```
[Mobile/Desktop] → [Proxmox Container] → [Windows LM Studio]
                         ↓
                   [Obsidian Vault]
```

- **Container** (Proxmox): FastAPI app on port 8000
- **LM Studio** (Windows `192.168.86.2:1234`): Local LLM API (NOT in container)
- **Vault**: Obsidian markdown files (mounted into container)

### 2. **LM Studio is External**
**CRITICAL**: The LLM runs on a separate Windows PC, NOT in the container.
- Location: `http://192.168.86.2:1234`
- Model: Qwen2.5-Coder-14B (or similar)
- Container makes HTTP requests to this external service
- User needs LM Studio running on Windows host before starting container

### 3. **Obsidian Integration**
The application **generates** Obsidian markdown files. Requirements:
- Templates in app **MUST** match templates in `the-reserve/Cellar/9_Templates/`
- Field names **MUST** match FileClass definitions in `the-reserve/Cellar/8_FileClass/`
- fileClass values are case-sensitive and used by DataviewJS queries

## Deployment Source

**Git is source of truth**. User expects:
1. Clone from git
2. Create `.env` from `.env.example`
3. Build and run with docker compose

Files in git:
- `Dockerfile`, `docker-compose.yml`
- `src/`, `config/`, `templates/`
- `.env.example` (template)

NOT in git:
- `.env` (created on server with actual secrets/paths)

## Required `.env` Configuration

```bash
WEB_SECRET_KEY=<generate new: openssl rand -hex 32>
VAULT_HOST_PATH=/path/to/the-reserve  # CRITICAL - where vault is on Proxmox
LM_STUDIO_HOST=192.168.86.2           # Windows host IP
LM_STUDIO_PORT=1234
WEB_PORT=8000
OBSIDIAN_PORT=8080
```

## Known Gotchas (from WSL2 Development)

### Port Binding MUST be Explicit
```yaml
ports:
  - "0.0.0.0:8000:8000"  # NOT just "8000:8000"
```
Without `0.0.0.0`, external devices can't reach the service.

### Volume Permissions
Container runs as `appuser` (UID 1000). If vault mount has permission issues:
```bash
chown -R 1000:1000 /path/to/vault
```

### First-Time Volume Creation
If container fails with "Permission denied: /app/logs/web_server.log":
```bash
docker compose down -v  # Remove volumes
docker compose up -d     # Recreate with proper ownership
```

## Verification Steps

After deployment:
```bash
# 1. Container health
docker compose ps
# Should show: Up X seconds (healthy)

# 2. Health endpoint
curl http://localhost:8000/api/v1/health
# Expected: {"status":"healthy",...}

# 3. LM Studio connectivity FROM container
docker compose exec web curl http://192.168.86.2:1234/v1/models
# Should return JSON with available models

# 4. External access (from mobile/laptop)
curl http://<proxmox-ip>:8000/api/v1/health
# Should work (tests firewall + port binding)
```

## Common Issues & Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Container restart loop | Permission error on /app/logs | `docker compose down -v && docker compose up -d` |
| Can't access from mobile | Port not bound to 0.0.0.0 | Check docker-compose.yml has `0.0.0.0:8000:8000` |
| "LM Studio unreachable" in logs | Windows host unreachable | 1. Verify LM Studio running<br>2. Test: `curl http://192.168.86.2:1234/v1/models` from Proxmox |
| Vault files not found | Wrong VAULT_HOST_PATH | Check path in `.env` matches actual vault location |

## User's Development Setup (Reference)

- **OS**: Windows 11 + WSL2 (Ubuntu)
- **Docker**: Docker Desktop with WSL2 backend
- **Networking**: WSL2 mirrored networking mode
- **Current Working Setup**: Container on WSL2, accessible from mobile at `192.168.86.2:8000`

User confirmed:
- ✅ Mobile access works
- ✅ LM Studio connectivity works
- ✅ Application is healthy

## What User Expects from You

1. **Pull from git** (don't ask for files, they're in the repository)
2. **Create `.env`** from `.env.example` with Proxmox-specific paths
3. **Deploy** with docker compose
4. **Verify** all 4 verification steps pass
5. **Troubleshoot** if any issues arise

## Key Files to Reference

- `DEPLOYMENT.md` - Full deployment guide (in repo)
- `.env.example` - Environment variable template
- `docker-compose.yml` - Service definition
- `config/system.yaml` - System defaults
- `config/user.yaml` - User overrides

## Questions to Ask User (if needed)

1. Where is the Obsidian vault on Proxmox? (for `VAULT_HOST_PATH`)
   - Is it NFS mounted?
   - Local storage?
   - SMB/CIFS mount?
2. What's the Proxmox host's IP address? (for external access verification)
3. Is LM Studio currently running on Windows host?

## Final Notes

- This is a **working application** - don't make architectural changes
- Configuration is via **environment variables** and **config/*.yaml**
- The user knows their setup works on WSL2, trusts the Docker configuration
- Focus on **deployment**, not redesign

Good luck! The setup is well-documented and tested. Most issues are environment/path related.
