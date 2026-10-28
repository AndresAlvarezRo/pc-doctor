#!/usr/bin/env bash
# habilitar-sensores.sh: habilita SMART y sensores extra para pc-doctor. Hay que ejecutarlo con sudo:
#   sudo bash habilitar-sensores.sh
# Es idempotente (se puede repetir). Lo que hace, en orden:
#   1. Instala smartmontools (SMART de los discos).
#   2. Carga el módulo drivetemp (temperatura de los discos SATA) y lo deja permanente.
#   3. Prueba el módulo nct6775 (voltajes de la placa). Solo lo deja permanente si aparece un sensor real.
#   4. Crea /etc/sudoers.d/pc-doctor con permiso SOLO para leer el SMART de tus discos, con esos argumentos exactos.
# No toca el arranque, el firmware ni ningún otro archivo del sistema.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Ejecutalo con sudo: sudo bash $0"; exit 1; }
USUARIO="${SUDO_USER:-}"
[ -n "$USUARIO" ] && [ "$USUARIO" != "root" ] || { echo "No pude determinar tu usuario (SUDO_USER vacío)."; exit 1; }
MODULOS=/etc/modules-load.d/pc-doctor.conf
hwmon_nombres() { cat /sys/class/hwmon/hwmon*/name 2>/dev/null | sort | paste -sd' '; }

echo "== 1/4 smartmontools"
if command -v smartctl >/dev/null; then echo "ya instalado: $(smartctl --version | head -1)"; else apt-get install -y smartmontools; fi

echo "== 2/4 drivetemp (temperatura de discos SATA)"
modprobe drivetemp && echo "cargado"
touch "$MODULOS"; grep -qx drivetemp "$MODULOS" || echo drivetemp >> "$MODULOS"

echo "== 3/4 nct6775 (voltajes de la placa)"
antes="$(hwmon_nombres)"
if modprobe nct6775 2>/tmp/nct6775.err; then
  despues="$(hwmon_nombres)"
  if [ "$antes" != "$despues" ] && echo "$despues" | grep -q nct; then
    echo "OK: apareció un sensor ($despues). Se deja permanente."
    grep -qx nct6775 "$MODULOS" || echo nct6775 >> "$MODULOS"
  else
    echo "El módulo cargó pero no apareció ningún sensor: se descarga."
    modprobe -r nct6775 || true
  fi
else
  echo "nct6775 no pudo cargarse: $(cat /tmp/nct6775.err)"
  echo "Si el mensaje habla de un conflicto de recursos ACPI, haría falta el parámetro de arranque acpi_enforce_resources=lax."
  echo "No lo aplico automáticamente: toca el arranque y lo tenés que decidir vos."
fi
rm -f /tmp/nct6775.err

echo "== 4/4 permiso mínimo para leer SMART sin contraseña"
SMARTCTL="$(command -v smartctl)"
TMP="$(mktemp)"
{
  echo "# pc-doctor: lectura de SMART de solo lectura. Argumentos exactos; no permite ninguna otra opción ni dispositivo."
  lineas=()
  for blk in /sys/block/*; do
    n="$(basename "$blk")"
    case "$n" in
      sd[a-z]*|hd[a-z]*|vd[a-z]*) lineas+=("$SMARTCTL -j -H -A /dev/$n") ;;
      nvme[0-9]*n[0-9]*)          lineas+=("$SMARTCTL -j -H -A /dev/${n%%n[0-9]*}") ;;
    esac
  done
  [ "${#lineas[@]}" -gt 0 ] || { echo "No encontré discos." >&2; exit 1; }
  printf '%s ALL=(root) NOPASSWD: ' "$USUARIO"
  ( IFS=','; echo "${lineas[*]}" | sed 's/,/, /g' )
} > "$TMP"
visudo -cf "$TMP" >/dev/null || { echo "El archivo sudoers generado no es válido; no se instala."; rm -f "$TMP"; exit 1; }
install -m 0440 -o root -g root "$TMP" /etc/sudoers.d/pc-doctor
rm -f "$TMP"
echo "instalado /etc/sudoers.d/pc-doctor:"; sed 's/^/   /' /etc/sudoers.d/pc-doctor

echo
echo "== Resultado"
echo "sensores hwmon ahora: $(hwmon_nombres)"
sudo -u "$USUARIO" sudo -n "$SMARTCTL" -j -H -A /dev/sda >/dev/null 2>&1; r=$?
# smartctl devuelve un código de bits (no 0) cuando hay avisos; solo 1 = comando mal formado, y sudo falla con 1 si pide contraseña.
echo "prueba de lectura SMART sin contraseña (/dev/sda): código $r ($( [ "$r" -ne 1 ] && echo OK || echo REVISAR))"
echo "Para deshacerlo todo: sudo rm /etc/sudoers.d/pc-doctor $MODULOS && sudo apt remove smartmontools"
