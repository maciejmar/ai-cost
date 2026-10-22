# Company AI OS — Makefile
# Uruchamiaj na serwerze webaby lub serwer GPU

.PHONY: up down infra agents logs ps pull gateway gateway-down gateway-test

# ─── Webaby: infrastruktura (PostgreSQL, Redis, RabbitMQ, Prometheus, Grafana) ──
infra:
	docker compose -f docker-compose.webaby.yml up -d

infra-down:
	docker compose -f docker-compose.webaby.yml down

# ─── Webaby: infrastruktura + agenty ────────────────────────────────────────────
agents:
	docker compose -f docker-compose.webaby.yml --profile agents up -d

agents-down:
	docker compose -f docker-compose.webaby.yml --profile agents down

# ─── Webaby: infrastruktura + keycloak ──────────────────────────────────────────
keycloak:
	docker compose -f docker-compose.webaby.yml --profile keycloak up -d

# ─── Webaby: AIGateway-X (bramka AI + dashboard) ───────────────────────────────
gateway:
	docker compose -f docker-compose.webaby.yml --env-file .env.agents --profile gateway up -d --build

gateway-down:
	docker compose -f docker-compose.webaby.yml --env-file .env.agents --profile gateway stop gateway gateway-ui

gateway-test:
	cd gateway && python -m pytest -q

gateway-keys:
	@echo "GATEWAY_JWT_SECRET=$$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
	@echo "GATEWAY_ENCRYPTION_KEY=$$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"

# ─── GPU serwer ─────────────────────────────────────────────────────────────────
gpu:
	docker compose -f docker-compose.gpu.yml up -d

gpu-down:
	docker compose -f docker-compose.gpu.yml down

# ─── Logi ───────────────────────────────────────────────────────────────────────
logs:
	docker compose -f docker-compose.webaby.yml logs -f --tail=100

logs-gpu:
	docker compose -f docker-compose.gpu.yml logs -f --tail=100

# ─── Status ─────────────────────────────────────────────────────────────────────
ps:
	docker compose -f docker-compose.webaby.yml ps

# ─── Update ─────────────────────────────────────────────────────────────────────
pull:
	docker compose -f docker-compose.webaby.yml pull
	docker compose -f docker-compose.gpu.yml pull

# ─── Ollama — pobierz modele na GPU ─────────────────────────────────────────────
ollama-models:
	docker compose -f docker-compose.gpu.yml exec ollama ollama pull llama3.3:70b-instruct-q4_K_M
	docker compose -f docker-compose.gpu.yml exec ollama ollama pull mistral:7b
	docker compose -f docker-compose.gpu.yml exec ollama ollama pull nomic-embed-text

# ─── Generowanie kluczy WireGuard ───────────────────────────────────────────────
wireguard-keygen:
	@echo "=== OVH VPS ===" && wg genkey | tee /tmp/ovh.key | wg pubkey
	@echo "=== Webaby ===" && wg genkey | tee /tmp/webaby.key | wg pubkey
	@echo "=== GPU ===" && wg genkey | tee /tmp/gpu.key | wg pubkey
	@echo "Klucze prywatne w /tmp/*.key — wpisz do wireguard/*.conf"
