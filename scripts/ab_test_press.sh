#!/usr/bin/env bash
# A/B: las pulsaciones hacen avanzar el juego?
#
# Esto parece obvio pero no lo es, y la trampa importa: el codigo hace
# "if (presses.empty()) return;", asi que SIN guion el pad no se instala
# y el guest no ve ningun dispositivo de juego. Un control de "sin
# pulsaciones" hecho asi compara dos cosas a la vez:
#
#   1. que haya un pad conectado
#   2. que se pulse algo
#
# El control justo es un guion que instala el pad pero que nunca dispara:
# un gesto programado mas alla del final de la corrida ("9999:0x1000").
# El guest ve el mismo dispositivo, pero ningun boton baja.
#
# Otras dos trampas, ya Pagadas en el codigo pero no en el shell:
#
#   - El juego necesita un X server. Sin DISPLAY muere en 0.03 s con
#     "No available video device", sin log y sin crash: el fallo es
#     silencioso y el A/B da numeros identicos siempre. Por eso
#     --video_driver=offscreen, que es el driver de SDL que no necesita X.
#   - "mcla_*.log" tambien matchea "mcla_NNN.1.log", que es la parte
#     ROTADA del log y por tanto ANTERIOR. Hay que excluirla y leer
#     todas las partes en orden cronologico.
#
# Uso:
#   scripts/ab_test_press.sh [segundos] [rondas]
#
#   scripts/ab_test_press.sh              # 180s por corrida
#   scripts/ab_test_press.sh 300 4        # 300s, 4 rondas
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TIMEOUT="${1:-180}"
RONDAS="${2:-3}"

GUION="3:0x1000,6:0x1000,9:0x0010,12:0x1000,15:0x0008,18:0x1000,21:0x0010,24:0x1000,27:0x0001,30:0x1000,33:0x0010,36:0x1000,39:0x0008,42:0x1000,45:0x0010,48:0x1000"
NUNCA="9999:0x1000"
STICK="3:s:0:-1,6:0x1000,9:s:0:1,12:0x1000,15:s:-1:0,18:0x1000,21:s:1:0,24:0x1000,27:0x0010,30:0x1000,33:s:0:-1,36:0x1000,39:s:0:1,42:0x1000"

[ -x out/pc/mcla ] || { echo "ERROR: falta out/pc/mcla" >&2; exit 1; }
[ -d "$HOME/midnight-club-la" ] || { echo "ERROR: falta la copia del juego" >&2; exit 1; }

corre() {
  local etiqueta="$1" guion="$2"
  # La arena del invitado va en tmpfs: sin limpiarla, varias ejecuciones
  # seguidas agotan /dev/shm y el fallo aparece como SIGBUS.
  rm -f /dev/shm/xenia_memory_* 2>/dev/null
  rm -rf out/runtime/user out/runtime/cache
  mkdir -p out/runtime/user out/runtime/cache

  local antes
  antes=$(ls out/pc/logs/mcla_*.log 2>/dev/null | wc -l)

  MCLA_PAD_PRESS="$guion" timeout "$TIMEOUT" ./out/pc/mcla \
    --game_data_root="$HOME/midnight-club-la" \
    --user_data_root="$PWD/out/runtime/user" \
    --cache_root="$PWD/out/runtime/cache" \
    --metadata_root="$PWD/out/runtime/metadata" \
    --log_level=info --headless=true --mnk_mode=true --user_language=1 \
    --video_driver=offscreen >/dev/null 2>&1

  local log
  log=$(ls -t out/pc/logs/mcla_*.log 2>/dev/null | grep -v '\.[0-9]*\.log$' | head -1)
  if [ -z "$log" ] || [ "$(ls out/pc/logs/mcla_*.log 2>/dev/null | wc -l)" -le "$antes" ]; then
    printf '  %-32s SIN LOG (la corrida no arranco?)\n' "$etiqueta"
    return
  fi
  # Todas las partes del log, en orden cronologico.
  local texto
  texto=$(cat "$log" $(ls out/pc/logs/mcla_*.log 2>/dev/null | grep -E '\.[0-9]+\.log$' | sort -t. -k2 -n) 2>/dev/null)

  local pipes fatal gestos save
  pipes=$(printf '%s' "$texto" | grep -c "Creating graphics pipeline")
  fatal=$(printf '%s' "$texto" | grep -c "invalid or unregistered")
  gestos=$(printf '%s' "$texto" | grep -c "scripted gamepad buttons")
  if [ -n "$(find out/runtime/user -name '*.sav' 2>/dev/null)" ]; then save="SI"; else save="no"; fi
  printf '  %-32s pipes=%4s fatal=%s gestos=%3s save=%s\n' \
    "$etiqueta" "$pipes" "$fatal" "$gestos" "$save"
}

echo "==> A/B de pulsaciones (${TIMEOUT}s por corrida, $RONDAS rondas)"
for ronda in $(seq 1 "$RONDAS"); do
  echo "--- ronda $ronda/$RONDAS ---"
  corre "A: sin pad en absoluto"   ""
  corre "B: pad presente, no pulsa" "$NUNCA"
  corre "C: 16 pulsaciones"          "$GUION"
  corre "D: stick 4 dir + A + START" "$STICK"
done

cat <<'NOTA'

Como leerlo:
  - A contra B dice si tener el pad conectado cambia algo. No cambia:
    el avance lo causan las pulsaciones.
  - B contra C dice si las pulsaciones cambian algo. Cambian: del orden
    de 100 pipelines mas, la diferencia entre el menu y la partida.
  - El conteo absoluto de pipelines es RUIDOSO: la misma corrida de
    control dio 299, 265 y 556 en corridas distintas. Comparar
    condiciones, nunca contra un numero guardado de otra sesion.
  - "save=SI" es la señal fuerte: el juego entro en una partida de
    verdad, no en un menu.
NOTA
