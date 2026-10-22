#!/usr/bin/env bash
# Hunting de huecos que solo se alcanzan al pulsar.
#
# El ciclo normal (scripts/fix_gap_crashes.py) corre el juego sin tocar
# nada, asi que nunca ve los huecos que estan en el codigo de input: el
# 0x82554080, que colgaba al pulsar en el movil, es uno de ellos.
#
# Este script es el hunting de esos: le da al juego un guion de
# pulsaciones (el mando de prueba de src/mcla_scripted_pad.cpp) y vigila
# los logs en busca del crash. Si aparece, imprime la direccion del hueco
# para declararla en mcla_analysis.toml.
#
# Que el guion sea largo y variado importa: con 16 pulsaciones el juego
# llega a leer 'xarchive_audlo.rpf', un archivo que sin pulsaciones no
# lee nunca. Cada pantalla nueva es codigo nuevo, y el codigo nuevo
# puede tener huecos.
#
# Uso:
#   scripts/hunt_gaps_with_press.sh [rondas] [guion]
#
#   scripts/hunt_gaps_with_press.sh
#   scripts/hunt_gaps_with_press.sh 3 "3:0x1000,7:0x1000,11:0x0010"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RONDAS="${1:-3}"
# Un guion largo y variado: A, START y las flechas, que son las que
# mueven los menus.
GUION="${2:-3:0x1000,7:0x1000,11:0x0010,15:0x1000,19:0x0008,23:0x1000,27:0x0010,31:0x1000,35:0x0001,39:0x1000,43:0x0010,47:0x1000,51:0x0008,55:0x1000,59:0x0010,63:0x1000}"
TIMEOUT="${MCLA_HUNT_TIMEOUT:-150}"

cd "$ROOT"

echo "==> hunting de huecos con pulsaciones"
echo "    rondas:   $RONDAS"
echo "    guion:    $GUION"
echo "    timeout:  ${TIMEOUT}s por ronda"
echo

for ronda in $(seq 1 "$RONDAS"); do
  echo "--- ronda $ronda/$RONDAS ---"
  # El ciclo se encarga de compilar, ejecutar, leer todas las partes del
  # log (incluidas las rotadas) y declarar el hueco si lo encuentra.
  python3 scripts/fix_gap_crashes.py \
    --pulsar "$GUION" \
    --timeout "$TIMEOUT" \
    --max-rondas 1 2>&1 | tail -20
  echo
done

echo "==> resumen de lo que se ha leido con pulsaciones"
# Los archivos que el juego solo lee si avanza: la senal de que ha
# llegado a contenido nuevo.
LAST="$(ls -t out/pc/logs/mcla_*.log 2>/dev/null | grep -v '\.[0-9]*\.log$' | head -1)"
if [ -n "$LAST" ]; then
  for f in xarchive_audlo.rpf xarchive_audio.rpf xarchive_music.rpf xarchive_cache.rpf; do
    n="$(grep -c "$f" "$LAST" 2>/dev/null || true)"
    printf '    %-24s %s\n' "$f" "${n:-0}"
  done
fi

# Un mc4.sav significa que el juego entro en una partida de verdad, no
# en un menu. Es la senal de avance fuerte.
if find out/runtime/user -name '*.sav' 2>/dev/null | grep -q .; then
  echo "    partida guardada:    SI (llego al free roam)"
else
  echo "    partida guardada:    no (sigue en los menus)"
fi
