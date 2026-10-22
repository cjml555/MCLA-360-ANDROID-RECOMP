#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Declara los huecos >= 8 bytes en el analysis.toml del proyecto.

El problema
-----------
Quedan 633 huecos de codigo >= 8 bytes sin dueno: bloques reales de
codigo que el descubrimiento automatico no atribuyo a ninguna funcion.
El guest puede llamar ahi por una puntero o una vtable, y entonces
sale:

    [FATAL] Call to invalid or unregistered function at guest address 0x...

El hunting con el mando de prueba ya llega a la ciudad y no encuentra
ninguno: esos 633 no son de las pantallas que alcanzan las pulsaciones,
o no se llaman todavia.

La solucion
-----------
Declararlos en el analysis.toml, que es donde el Discover los reclama.
Y declararlos EN TRAMOS DE 8 BYTES, no solo el inicio: un hueco puede
contener varias funciones seguidas (thunks de 8 y 16 bytes), y declarar
solo el inicio hace que el Discover se lo trague entero y el crash se
mueva a +8, +24, +64... bytes. El patron ya esta en el analysis.toml
actual: cada hueco que revento tiene 4 entradas seguidas.

Por que >= 8 bytes y no todos
-----------------------------
Los huecos de 4 bytes son el relleno minimo entre dos funciones
consecutivas (padding o thunk). Hay 14543 y no bloquean: el guest casi
nunca llama ahi, y declararlos todos haria el codegen mas lento y mas
fragil. Los de 8 o mas si son bloques de codigo de verdad.

Como decide si funciona
------------------------
El codegen es el judge: si al declarar un hueco se rompe, el codegen
falla y el juego deja de arrancar. Asi que se declara de golpe, se
genera, y se comprueba que el juego sigue igual (mismos pipelines, 0
fatales). Si el codegen se rompe, se revierte el lote.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/jhon/MCLA-360-ANDROID-RECOMP")
ANALYSIS = ROOT / "mcla_analysis.toml"
INFORME = ROOT / "out/huecos_now.txt"
LOG_DIR = ROOT / "out/pc/logs"
GAME_ROOT = Path.home() / "midnight-club-la"

# La cabecera del analysis.toml: los ajustes que el juego necesita.
CABECERA = """# Initial analysis found direct branches to these executable addresses without
# function ownership. Declare the destinations and let discovery find bounds.
# Keep registers in the shared PPC context for this initial bring-up.
cr_as_local = false
xer_as_local = false
ctr_as_local = false
non_volatile_as_local = false

[functions]
"""


def huecos_grandes(minimo=8):
    """Los huecos de >= minimo bytes, con su inicio y tamano."""
    texto = INFORME.read_text(encoding="utf-8")
    # Del bloque "TODOS los huecos >= N bytes:" del final del informe.
    bloque = texto.split("TODOS los huecos")[-1]
    patron = re.compile(r"^\s+(0x[0-9A-F]+)\s+(\d+) bytes\s+\(tras (0x[0-9A-F]+), "
                         r"antes de (0x[0-9A-F]+)\)", re.M)
    return [(int(a, 16), int(s), int(i, 16), int(d, 16))
            for a, s, i, d in patron.findall(bloque) if int(s) >= minimo]


def claves_actuales():
    texto = ANALYSIS.read_text(encoding="utf-8")
    return {m.lower() for m in re.findall(r'"(0x[0-9A-Fa-f]+)"\s*=', texto)}


def escribir_analysis(entradas, comentario):
    """Reescribe el analysis.toml con las entradas dadas.

    Se conservan los comentarios y las entradas que ya habia: solo se
    anaden las nuevas al final, en su propio bloque.
    """
    texto = ANALYSIS.read_text(encoding="utf-8")
    # Lo que hay ahora, normalizado a minuscula para no duplicar. Las
    # claves son cadenas ("0x82554080") y las direcciones enteras.
    ya = claves_actuales()
    nuevas = [e for e in entradas if f"0x{e:08x}" not in ya]
    if not nuevas:
        return 0
    if not texto.rstrip().endswith("}"):
        texto = texto.rstrip() + "\n"
    bloque = [f"\n# --- {comentario} ---\n"]
    bloque += [f'"0x{e:08X}" = {{ }}\n' for e in nuevas]
    ANALYSIS.write_text(texto + "".join(bloque), encoding="utf-8")
    return len(nuevas)


def codegen():
    """Regenera el codigo. Devuelve (ok, salida)."""
    r = subprocess.run(
        ["cmake", "--build", "out/pc", "--target", "mcla_codegen", "--parallel", "4"],
        cwd=ROOT, capture_output=True, text=True, timeout=1800)
    return r.returncode == 0, (r.stdout + r.stderr)[-4000:]


def probar(minutos=3):
    """Corre el juego y dice como fue: pipelines y fatales."""
    for f in Path("/dev/shm").glob("xenia_memory_*"):
        try:
            f.unlink()
        except OSError:
            pass
    cmd = ["./out/pc/mcla",
           f"--game_data_root={GAME_ROOT}",
           f"--user_data_root={ROOT}/out/runtime/user",
           f"--cache_root={ROOT}/out/runtime/cache",
           f"--metadata_root={ROOT}/out/runtime/metadata",
           "--log_level=info", "--headless=true", "--mnk_mode=true",
           "--user_language=1", "--video_driver=offscreen"]
    try:
        subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       timeout=minutos * 60)
    except subprocess.TimeoutExpired:
        pass
    logs = sorted(LOG_DIR.glob("mcla_*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return None
    log = logs[-1]
    texto = log.read_text(errors="replace")
    return {
        "log": log.name,
        "pipelines": texto.count("Creating graphics pipeline"),
        "fatales": texto.count("invalid or unregistered"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=8,
                    help="tamano minimo del hueco (8 = codigo real)")
    ap.add_argument("--tramos", type=int, default=0,
                    help="declarar solo los N huecos mas grandes (0 = todos)")
    ap.add_argument("--piloto", action="store_true",
                    help="declarar solo 5 huecos y probar, sin tocar mas")
    ap.add_argument("--no-probar", action="store_true")
    args = ap.parse_args()

    huecos = huecos_grandes(args.min)
    if not huecos:
        print("no hay huecos >= %d en el informe" % args.min)
        return 1
    print(f"huecos >= {args.min} bytes: {len(huecos)}")

    # Backup antes de tocar nada.
    backup = ROOT / "out" / "mcla_analysis.toml.bak"
    shutil.copy2(ANALYSIS, backup)
    print(f"backup en {backup}")

    if args.tramos:
        huecos = sorted(huecos, key=lambda h: -h[1])[:args.tramos]
        print(f"  (solo los {len(huecos)} mas grandes)")
    if args.piloto:
        huecos = huecos[:5]
        print("  (piloto: 5 huecos)")

    # Las entradas: cada hueco, en tramos de 8 bytes, desde su inicio.
    entradas = []
    for inicio, tam, _, _ in huecos:
        for off in range(0, tam, 8):
            entradas.append(inicio + off)
    print(f"entradas a declarar: {len(entradas)}")

    n = escribir_analysis(entradas, "Auto: huecos >= %d bytes, en tramos de 8" % args.min)
    print(f"declaradas: {n}")

    ok, salida = codegen()
    if not ok:
        print("\nCODEGEN ROTO: se revierte")
        print(salida[-2500:])
        shutil.copy2(backup, ANALYSIS)
        return 2
    print("codegen OK")

    if not args.no_probar:
        r = probar()
        if r:
            print(f"juego: {r['log']}  pipelines={r['pipelines']}  "
                  f"fatales={r['fatales']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
