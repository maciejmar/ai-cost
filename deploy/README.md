# CI/CD — AIGateway-X

Produkcja: **https://ai-cost.webaby.io**, serwer `95.158.64.196` (Ubuntu, systemowy nginx 1.24 → kontenery na `127.0.0.1`).

| Workflow | Kiedy | Co robi |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | każdy PR (i jako krok deployu) | testy jednostkowe + e2e bramki (Postgres/Redis jako services, atrapa OpenAI/Anthropic), build dashboardu, walidacja Compose, `compileall shared/`, test budowy obrazów |
| [`deploy.yml`](../.github/workflows/deploy.yml) | push na `master` / ręcznie | CI → obrazy `ghcr.io/maciejmar/ai-cost/{gateway,gateway-ui}:<sha>` + `latest` → SSH na serwer → [`deploy.sh`](deploy.sh) |

```
internet ──443──▶ nginx (95.158.64.196) ── /v1, /api ──▶ 127.0.0.1:8190  gateway     ┐ docker compose
                  ai-cost.webaby.io      └─ /        ──▶ 127.0.0.1:3190  gateway-ui  │ (profil gateway)
                                                          postgres, redis (sieć wewnętrzna) ┘
```

`deploy.sh` na serwerze: `docker compose pull` + `up -d` dla `gateway` i `gateway-ui`, healthcheck
(`/health` bramki i `/login` dashboardu, do 90 s). Gdy nie przejdzie, wraca do poprzedniego tagu
(`.deploy/gateway-tag`), a job kończy się błędem.

**Rollback ręczny:** Actions → Deploy → Run workflow → `tag` = SHA commita, który ma wrócić.

## Jednorazowa konfiguracja serwera 95.158.64.196

### 1. Użytkownik i katalog wdrożenia

```bash
ss -ltnp | grep -E ':(8190|3190)\b'                     # porty muszą być wolne (8090 zajmuje inny kontener)
docker compose version                                  # potrzebna wtyczka compose v2

sudo useradd -m -s /bin/bash -G docker deploy
sudo mkdir -p /opt/agentic-ai-os && sudo chown deploy: /opt/agentic-ai-os
# jako deploy — plik z sekretami (nigdy nie trafia do repo ani do GitHuba):
nano /opt/agentic-ai-os/.env.agents && chmod 600 /opt/agentic-ai-os/.env.agents
```

Minimum w `.env.agents`: `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `REDIS_URL=redis://:<hasło>@redis:6379/0`,
`GATEWAY_JWT_SECRET`, `GATEWAY_ENCRYPTION_KEY` (wygeneruj: `make gateway-keys`), `GATEWAY_ALLOW_SIGNUP=false`,
`GATEWAY_HOST_PORT=8190`, `GATEWAY_UI_HOST_PORT=3190` (muszą się zgadzać z `upstream` w `nginx/ai-cost.webaby.io.conf`).
Opcjonalnie `LITELLM_URL` / `LITELLM_MASTER_KEY` dla lokalnych modeli na serwerze GPU.

### 2. nginx + certyfikat

Kontenery publikują porty tylko na `127.0.0.1`, więc z zewnątrz ruch wchodzi wyłącznie przez nginx.

```bash
sudo certbot certonly --nginx -d ai-cost.webaby.io      # DNS już wskazuje na ten serwer
sudo cp nginx/ai-cost.webaby.io.conf /etc/nginx/sites-available/ai-cost.webaby.io
sudo ln -s /etc/nginx/sites-available/ai-cost.webaby.io /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Odnawianie certyfikatu robi istniejący timer certbota (`systemctl list-timers | grep certbot`).

### 3. Klucz SSH dla GitHub Actions

```bash
ssh-keygen -t ed25519 -f deploy_key -N "" -C "github-actions-deploy"
ssh-copy-id -i deploy_key.pub deploy@95.158.64.196
ssh-keyscan -t ed25519 95.158.64.196 > known_hosts      # porównaj z: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

### 4. GitHub → Settings → Environments → `production`

| Nazwa | Typ | Wartość |
|---|---|---|
| `DEPLOY_HOST` | secret | `95.158.64.196` |
| `DEPLOY_USER` | secret | `deploy` |
| `DEPLOY_SSH_KEY` | secret | zawartość `deploy_key` (prywatny) |
| `DEPLOY_KNOWN_HOSTS` | secret | zawartość `known_hosts` |
| `DEPLOY_JUMP_HOST` | secret, opcjonalny | tylko gdy SSH nie jest dostępne publicznie — np. `deploy@<host-pośredni>` |
| `DEPLOY_PATH` | variable | `/opt/agentic-ai-os` |

Zalecane: w tym samym środowisku włącz **Required reviewers**, żeby każde wdrożenie czekało na akceptację.

Obrazy w GHCR są prywatne i powiązane z repo (label `org.opencontainers.image.source`).
Serwer loguje się na czas wdrożenia tokenem `GITHUB_TOKEN` i wylogowuje na końcu.

### 5. Pierwsze uruchomienie

Push na `master` (albo Actions → Deploy → Run workflow). Po udanym wdrożeniu wejdź na
https://ai-cost.webaby.io i zarejestruj pierwsze konto — zostaje adminem. Rejestracja kolejnych
jest zablokowana przy `GATEWAY_ALLOW_SIGNUP=false`.
