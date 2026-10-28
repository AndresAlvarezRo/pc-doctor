#!/usr/bin/env bash
# Compila el frontend del dashboard a web/frontend/dist/. FastAPI sirve esos archivos estáticos: en producción no corre Node.
# Usa el Node aislado de ~/.local/share/pc-doctor/node (se puede cambiar con PC_DOCTOR_NODE). No necesita sudo.
#   bash web/construir.sh
set -euo pipefail
AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE="${PC_DOCTOR_NODE:-$HOME/.local/share/pc-doctor/node}"
[ -x "$NODE/bin/node" ] || { echo "No encuentro Node en $NODE. Ver BITACORA.md (sección Node instalado)."; exit 1; }
export PATH="$NODE/bin:$PATH"
cd "$AQUI/frontend"
echo "Node $(node --version), npm $(npm --version)"
# Instala exactamente las versiones de package-lock.json si todavía no hay node_modules
[ -d node_modules ] || npm ci --no-fund --no-audit
npm run build
echo "Listo: $AQUI/frontend/dist (lo sirve web/api.py; reiniciá el servicio si estaba corriendo)"
