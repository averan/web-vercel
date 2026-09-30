#!/usr/bin/env bash
# Conecta el asistente de la web de Vercel con el modelo de este Mac.
#   1. Arranca server.py y abre un túnel gratuito de Cloudflare.
#   2. Sube a GitHub la nueva dirección del túnel (backend.js) → Vercel se actualiza solo.
#   3. Al salir (Ctrl+C) deja backend.js vacío: la web muestra «asistente no disponible».
# El Mac debe estar encendido y oMLX en marcha.
# Uso:  ./servidor/publicar.sh
set -uo pipefail
cd "$(dirname "$0")"
REPO=$(git rev-parse --show-toplevel) || exit 1

bold=$'\033[1m'; green=$'\033[32m'; yellow=$'\033[33m'; red=$'\033[31m'; reset=$'\033[0m'
fail() { echo "${red}✗ $*${reset}"; exit 1; }
warn() { echo "${yellow}! $*${reset}"; }

[ -f .env ] || fail "Falta servidor/.env. Créalo con:  cp servidor/.env.example servidor/.env  y pon tu OMLX_API_KEY."
envget() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
PORT=$(envget PORT); PORT=${PORT:-5194}
OMLX_URL=$(envget OMLX_URL); OMLX_URL=${OMLX_URL:-http://127.0.0.1:8000}
SITIO_URL=$(envget SITIO_URL); SITIO_URL=${SITIO_URL:-https://web-vercel-zeta-red.vercel.app}

command -v cloudflared >/dev/null || fail "Falta cloudflared. Instálalo con:  brew install cloudflared"
curl -sf -m 5 "$OMLX_URL/health" >/dev/null || fail "oMLX no responde en $OMLX_URL. Arráncalo primero."
if lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "El puerto $PORT ya está en uso (¿otro publicar.sh abierto?). Ciérralo y vuelve a intentarlo."
fi

# Escribe backend.js con la dirección del túnel ('' = sin asistente) y lo sube a GitHub.
publish_backend() {
  printf "// Lo genera servidor/publicar.sh: dirección del backend del asistente ('' = no disponible).\nwindow.FAENA_BACKEND = '%s';\n" "$1" > "$REPO/backend.js"
  git -C "$REPO" diff --quiet -- backend.js && return 0
  git -C "$REPO" commit -q -m "$2" -- backend.js || return 1
  git -C "$REPO" pull -q --rebase --autostash >/dev/null 2>&1 || true
  git -C "$REPO" push -q
}

LOG=$(mktemp -t cloudflared)
cleanup() {
  trap - EXIT INT TERM
  echo; echo "Deteniendo…"
  kill "${SERVER_PID:-}" "${TUNNEL_PID:-}" "${AWAKE_PID:-}" 2>/dev/null
  rm -f "$LOG"
  if [ -n "${PUBLISHED:-}" ]; then
    publish_backend "" "Asistente: fuera de línea" \
      && echo "La web ahora muestra «asistente no disponible» (Vercel tarda ~30 s en actualizarse)." \
      || warn "No se pudo actualizar GitHub: la web seguirá apuntando al túnel cerrado hasta el próximo publicar.sh."
  fi
  echo "El asistente ya no está conectado."
}
trap cleanup EXIT INT TERM

python3 server.py & SERVER_PID=$!
sleep 1
kill -0 "$SERVER_PID" 2>/dev/null || fail "No se pudo arrancar server.py."

caffeinate -i -w $$ & AWAKE_PID=$!   # evita que el Mac se duerma mientras está conectado

echo "Abriendo túnel con Cloudflare…"
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" >"$LOG" 2>&1 & TUNNEL_PID=$!

URL=""
for _ in $(seq 1 45); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1)
  [ -n "$URL" ] && break
  kill -0 "$TUNNEL_PID" 2>/dev/null || break
  sleep 1
done
[ -n "$URL" ] || { cat "$LOG"; fail "No se pudo abrir el túnel (ver mensajes de arriba)."; }

echo "Túnel: $URL"
echo "Subiendo la nueva dirección a GitHub…"
publish_backend "$URL" "Asistente: nueva dirección del túnel" || fail "No se pudo subir backend.js a GitHub (revisa tu conexión o ejecuta git push a mano)."
PUBLISHED=1

echo "Esperando a que Vercel publique el cambio…"
LIVE=""
for _ in $(seq 1 60); do
  curl -sf -m 5 "$SITIO_URL/backend.js?t=$(date +%s)" | grep -qF "$URL" && { LIVE=1; break; }
  sleep 3
done

echo
if [ -n "$LIVE" ]; then
  echo "${bold}${green}✓ Asistente activo en la web:${reset}  ${bold}$SITIO_URL${reset}"
else
  warn "Vercel aún no muestra la nueva dirección. Revisa el despliegue en vercel.com; el asistente se activará cuando termine."
fi
echo "  Backend local:  http://localhost:$PORT"
echo "  Contactos:      python3 servidor/contactos.py listar"
echo "  Mantén este Mac encendido y oMLX en marcha. Ctrl+C para desconectar el asistente."
echo
echo "Consultas recibidas:"

wait "$SERVER_PID" "$TUNNEL_PID"
