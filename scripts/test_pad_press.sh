#!/usr/bin/env bash
# Prueba la pulsacion en el PC, sin movil.
#
# El port tiene un mando de prueba (src/mcla_scripted_pad.cpp) que el
# proyecto instala en el input system del SDK: publica un boton XInput
# en un temporizador, asi que el guest ve lo mismo que veria en el
# telefono. Sirve para dos cosas:
#
#   1. Comprobar que "PRESS >" avanza el titulo. En el movil eso exige
#      el dispositivo en primer plano y a alguien pulsando; aqui es un
#      comando.
#   2. Seguir hunting de huecos: los huecos que solo se alcanzan al
#      pulsar (el 0x82554080 lo era) no los ve el ciclo automatico,
#      porque el ciclo no pulsa nada.
#
# Los tiempos son relativos a la primera consulta del guest al pad, no
# al inicio de la ejecucion: el juego no mira el mando hasta que llega
# al titulo, unos 35 segundos despues de arrancar.
#
# Uso:
#   scripts/test_pad_press.sh [script-de-pulsaciones]
#
#   scripts/test_pad_press.sh                    # una pulsacion de A
#   scripts/test_pad_press.sh "2:0x1000,8:0x1000"  # secuencia
#
# Los scripts se escriben en MCLA_PAD_PRESS: "<segundos>:<mascara XInput>".
# La mascara es la de XInput, la misma que usa el overlay tactil:
# A = 0x1000, B = 0x2000, X = 0x4000, Y = 0x8000, START = 0x0010.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SCRIPT="${1:-2:0x1000}"
DURATION="${MCLA_PAD_TEST_SECONDS:-90}"
GAME_ROOT="${MCLA_GAME_ROOT:-$HOME/midnight-club-la}"

[ -d "$GAME_ROOT" ] || { echo "ERROR: no esta la copia del juego en $GAME_ROOT" >&2; exit 1; }
[ -x "$ROOT/out/pc/mcla" ] || { echo "ERROR: falta out/pc/mcla (cmake --build out/pc --target mcla)" >&2; exit 1; }

# La arena del invitado se respalda en tmpfs: sin limpiarla, varias
# ejecuciones seguidas agotan /dev/shm y el fallo aparece como SIGBUS.
rm -f /dev/shm/xenia_memory_* 2>/dev/null || true

LOG_DIR="$ROOT/out/pc/logs"
mkdir -p "$LOG_DIR"
BEFORE="$(ls -1 "$LOG_DIR" 2>/dev/null | wc -l)"

echo "==> pulsaciones: $SCRIPT  (durante ${DURATION}s)"
# --video_driver offscreen: el driver de video de SDL que no necesita un
# X server. Sin el, la corrida muere en 0.03 s con "No available video
# device" si no hay DISPLAY, y el fallo es silencioso: no hay log, y un
# A/B con ese fallo da numeros identicos siempre.
MCLA_PAD_PRESS="$SCRIPT" timeout "$DURATION" "$ROOT/out/pc/mcla" \
  --game_data_root="$GAME_ROOT" \
  --user_data_root="$ROOT/out/runtime/user" \
  --cache_root="$ROOT/out/runtime/cache" \
  --metadata_root="$ROOT/out/runtime/metadata" \
  --log_level=info --headless=true --mnk_mode=true --user_language=1 \
  --video_driver offscreen \
  > /dev/null 2>&1 || true

# El log nuevo es el mas reciente; tambien puede tener una parte rotada.
LOG="$(ls -t "$LOG_DIR"/*.log 2>/dev/null | head -1)"
if [ -z "$LOG" ]; then
  echo "ERROR: no hay log en $LOG_DIR" >&2
  exit 1
fi

echo
echo "==> log: $LOG"
grep -E "scripted gamepad (clock|buttons|pressing|installed|poll)" "$LOG" 2>/dev/null \
  | sed 's/.*mcla: /  /' || echo "  (el pad no se instalo: revisa MCLA_PAD_PRESS)"

PIPES="$(grep -c 'Creating graphics pipeline' "$LOG" 2>/dev/null | head -1 || true)"
FATALS="$(grep -cE 'FATAL|invalid or unregistered function' "$LOG" 2>/dev/null | head -1 || true)"
# grep -c imprime 0 y sale con codigo 1 cuando no hay coincidencias: el
# "|| true" evita que set -e aborte, y el head -1 recorta el "0" extra
# que genera el pipe.
PIPES="${PIPES:-0}"
FATALS="${FATALS:-0}"
echo
echo "  pipelines creados: $PIPES"
echo "  errores fatales:   $FATALS"

# Un guardado mc4.sav significa que el juego entro en una partida de
# verdad: llego al free roam, no a un menu. Es la senal de avance
# fuerte, mucho mas que el numero de pipelines.
if find "$ROOT/out/runtime/user" -name '*.sav' 2>/dev/null | grep -q .; then
  echo "  partida guardada:  SI (llego al free roam)"
else
  echo "  partida guardada:  no (sigue en los menus)"
fi

# Las partes rotadas del log tambien cuentan: el sink renombra el
# actual a .1.log al llegar a 5 MB, y su contenido es ANTERIOR.
ROTATED="$(ls -t "$LOG_DIR"/*.1.log 2>/dev/null | head -1)"
if [ -n "$ROTATED" ]; then
  echo "  log rotado:       $(basename "$ROTATED")"
fi

if [ "$FATALS" -gt 0 ]; then
  echo
  echo "==> la pulsacion ha encontrado un hueco. Direccion:"
  grep -oE "invalid or unregistered function at guest address 0x[0-9A-F]+" "$LOG" | head -3
  exit 1
fi
