#!/usr/bin/env bash
# Instala los hooks de git del proyecto: enlaza scripts/pre-commit en .git/hooks/. Se puede repetir sin problema.
#   bash scripts/instalar-hooks.sh
# Si ya había otro hook pre-commit, lo guarda como pre-commit.antes. Para desinstalar: rm "$(git rev-parse --git-path hooks)/pre-commit"
set -euo pipefail

RAIZ="$(git rev-parse --show-toplevel)"
cd "$RAIZ"
[ -f scripts/pre-commit ] || { echo "No encuentro scripts/pre-commit en $RAIZ"; exit 1; }
chmod +x scripts/pre-commit
HOOKS="$(git rev-parse --git-path hooks)"
mkdir -p "$HOOKS"
DESTINO="$HOOKS/pre-commit"

if [ -L "$DESTINO" ] && [ "$(readlink -f "$DESTINO")" = "$RAIZ/scripts/pre-commit" ]; then
  echo "El hook pre-commit ya estaba instalado: $DESTINO"
  exit 0
fi
if [ -e "$DESTINO" ] || [ -L "$DESTINO" ]; then
  mv "$DESTINO" "$DESTINO.antes"
  echo "Había otro hook pre-commit: lo guardé como $DESTINO.antes"
fi
ln -s "$(realpath --relative-to="$HOOKS" scripts/pre-commit)" "$DESTINO"
echo "Hook pre-commit instalado: $DESTINO -> scripts/pre-commit"
echo "Bloquea el commit si hay datos o secretos, archivos de más de 1 MiB o pruebas rápidas que fallan."
