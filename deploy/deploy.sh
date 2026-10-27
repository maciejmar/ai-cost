#!/usr/bin/env bash
# Wdrożenie AIGateway-X na serwerze webaby (wywoływane przez .github/workflows/deploy.yml).
#
#   deploy/deploy.sh <tag>
#
# Pobiera obrazy gateway + gateway-ui o podanym tagu, restartuje je i sprawdza healthcheck.
# Gdy healthcheck nie przejdzie — wraca do poprzednio wdrożonego tagu (.deploy/gateway-tag).
# Wymaga pliku .env.agents w katalogu wdrożenia. DEPLOY_SKIP_PULL=1 — test lokalny bez rejestru.
set -euo pipefail

TAG="${1:?Użycie: deploy.sh <tag>}"
cd "$(dirname "$0")/.."

ENV_FILE=.env.agents
[ -f "$ENV_FILE" ] || { echo "Brak $ENV_FILE w $(pwd)" >&2; exit 1; }

export IMAGE_PREFIX="${IMAGE_PREFIX:-ghcr.io/maciejmar/ai-cost}"

# Porty hosta — te same co w compose (GATEWAY_HOST_PORT / GATEWAY_UI_HOST_PORT w .env.agents)
# Jak compose: ostatnie wystąpienie, bez komentarza w linii (" # …") i końcowych spacji
env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1 | sed 's/[[:space:]]#.*$//; s/[[:space:]]*$//'; }
GATEWAY_PORT="$(env_value GATEWAY_HOST_PORT)"; GATEWAY_PORT="${GATEWAY_PORT:-8090}"
UI_PORT="$(env_value GATEWAY_UI_HOST_PORT)";   UI_PORT="${UI_PORT:-3100}"
COMPOSE=(docker compose -f docker-compose.webaby.yml --env-file "$ENV_FILE" --profile gateway)
SERVICES=(gateway gateway-ui)
STATE_DIR=.deploy
mkdir -p "$STATE_DIR"
PREVIOUS="$(cat "$STATE_DIR/gateway-tag" 2>/dev/null || true)"

deploy_tag() {
  export GATEWAY_TAG="$1"
  echo "==> Wdrażam $IMAGE_PREFIX/{gateway,gateway-ui}:$GATEWAY_TAG"
  if [ "${DEPLOY_SKIP_PULL:-0}" != "1" ]; then
    "${COMPOSE[@]}" pull "${SERVICES[@]}"
  fi
  "${COMPOSE[@]}" up -d --no-build "${SERVICES[@]}"
}

healthy() {
  for _ in $(seq 45); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$GATEWAY_PORT/health" && curl -fsS -o /dev/null "http://127.0.0.1:$UI_PORT/login"; then
      return 0
    fi
    sleep 2
  done
  return 1
}

deploy_tag "$TAG"
if healthy; then
  echo "$TAG" > "$STATE_DIR/gateway-tag"
  echo "==> OK: $TAG działa"
  docker image prune -f --filter "until=168h" >/dev/null || true
  exit 0
fi

echo "==> Healthcheck nie przeszedł dla $TAG" >&2
"${COMPOSE[@]}" logs --tail=80 "${SERVICES[@]}" >&2 || true

if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$TAG" ]; then
  echo "==> Rollback do $PREVIOUS" >&2
  deploy_tag "$PREVIOUS"
  if healthy; then
    echo "==> Rollback udany — działa $PREVIOUS" >&2
  else
    echo "==> Rollback też nie przeszedł healthchecku!" >&2
  fi
else
  echo "==> Brak poprzedniej wersji do rollbacku" >&2
fi
exit 1
