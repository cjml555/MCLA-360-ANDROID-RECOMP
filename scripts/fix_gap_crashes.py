#!/usr/bin/env python3
"""Itera sobre los huecos de codigo sin dueno de MCLA hasta que arranque.

Ciclo:
  1. Compila el binario de PC.
  2. Lo ejecuta en headless y lee el ultimo log.
  3. Si el fallo es "Call to invalid or unregistered function at guest address 0xADDR",
     busca el hueco que contiene ADDR y declara una entrada cada 8 bytes
     (un hueco puede contener varias funciones: el patron lo documenta
     tools/huecos.py del SDK).
  4. Repite hasta que no queden crashes de este tipo o no haya mas progreso.

Escribe las declaraciones en mcla_analysis.toml y regenera el codegen.

Con --pulsar, el juego recibe pulsaciones de boton (el mando de prueba de
src/mcla_scripted_pad.cpp). Sin ellas el ciclo no alcanza los huecos que
solo existen en el codigo de input: el 0x82554080, que colgaba al pulsar
en el movil, es uno de ellos. El script de pulsaciones son pares
"<segundos>:<mascara XInput>" separados por comas, y los segundos se
cuentan desde que el guest empieza a mirar el pad.

Los logs rotan: el sink del SDK escribe en `mcla_NNN.log` y al llegar a
5 MB renombra el actual a `mcla_NNN.1.log`. El contenido de `.1` es
ANTERIOR, asi que un crash temprano cae en la parte rotada: hay que
leerlas todas, no solo la mas reciente.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path("/home/jhon/MCLA-360-ANDROID-RECOMP")
SDK = Path("/home/jhon/nfsmw-android")
GAME_ROOT = Path("/home/jhon/midnight-club-la")
ANALYSIS = ROOT / "mcla_analysis.toml"
MARKER = "# --- Auto: gaps sin dueno (huecos.py) ---"

FATAL_RE = re.compile(
    r"Call to invalid or unregistered function at guest address 0x([0-9A-Fa-f]{8})")
GAP_RE = re.compile(
    r"^  (0x[0-9A-F]{8})\s+(\d+) bytes\s+\(tras (0x[0-9A-F]{8}), antes de (0x[0-9A-F]{8})\)",
    re.M)


def run(cmd, cwd=None, timeout=600, check=False):
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), timeout=timeout,
                          capture_output=True, text=True, check=check)


def limpiar_shm():
    """Libera la arena de memoria del guest (/dev/shm/xenia_memory_*).

    La arena del invitado se respaldan en tmpfs (5.8 GB aqui). Cada ejecucion
    deja un archivo de 4.8 GB, y varios ciclos seguidos agotan el espacio: el
    mmap del guest devuelve SIGBUS en lugar de ENOMEM, y el crash aparece como
    "Bus error" en libc, sin relacion con el codigo del juego. Limpiarlo entre
    rondas evita ese falso positivo.
    """
    for path in Path("/dev/shm").glob("xenia_memory_*"):
        try:
            path.unlink()
        except OSError:
            pass


def regenerar_huecos():
    """Relanza scripts/huecos.py sobre el codigo generado actual."""
    r = run(["python3", "scripts/huecos.py", "--gen", "generated/default",
             "--salida", "out/huecos.txt", "--toml", "out/huecos_functions.toml"],
            cwd=ROOT, timeout=600)
    return r.returncode == 0 and (ROOT / "out/huecos.txt").exists()


def gaps():
    """Devuelve {start: size} de los huecos >= 8 bytes leidos del informe."""
    report = ROOT / "out/huecos.txt"
    if not report.exists():
        return {}
    out = {}
    for start, size, _after, _before in GAP_RE.findall(report.read_text()):
        if int(size) >= 8:
            out[int(start, 16)] = int(size)
    return out


def rebuild():
    print("  * compilando...", flush=True)
    r = run(["cmake", "--build", "out/pc", "--target", "mcla", "--parallel", "4"], cwd=ROOT)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        raise SystemExit("fallo la compilacion")
    print("  * compilado", flush=True)


ORPHAN_RE = re.compile(r"^\s+(0x[0-9A-Fa-f]{8}) from (0x[0-9A-Fa-f]{8}):", re.M)


def regenerate(max_intentos=8):
    """Regenera el codegen resolviendo las ramas huerfanas que reporto el
    validador.

    El analizador solo valida ramas DIRECTAS. Una rama a un destino que
    ninguna funcion posee sale como "UnresolvedCall": declararlo en el
    analysis TOML deja que el descubrimiento le encuentre limites. Es
    iterativo: declarar una direccion cambia los limites de sus vecinas y
    aparece otro destino, normalmente a pocos bytes.
    """
    for intento in range(1, max_intentos + 1):
        print(f"  * regenerando codegen (~70s), intento {intento}...", flush=True)
        r = run(["./out/pc/rexglue", "codegen", "mcla_manifest.toml"], cwd=ROOT, timeout=900)
        salida = r.stdout + r.stderr
        if r.returncode == 0 and "Validation failed" not in salida:
            m = re.search(r"Codegen summary: (\d+) written, (\d+) unchanged", r.stdout)
            print(f"  * codegen: {m.group(0) if m else 'ok'}", flush=True)
            return True
        destinos = sorted({int(d, 16) for d, _ in ORPHAN_RE.findall(salida)})
        if not destinos:
            print(salida[-2500:], flush=True)
            raise SystemExit("fallo el codegen por otra causa")
        print(f"  * validacion fallo con {len(destinos)} destino(s) sin dueno: "
              + ", ".join(f"0x{d:08X}" for d in destinos), flush=True)
        nuevas = declare(destinos)
        if not nuevas:
            print("  * sin progreso en las ramas huerfanas: parando", flush=True)
            return False
    print("  * se agotaron los intentos del codegen", flush=True)
    return False


LOG_ROTATED_RE = re.compile(r"^mcla_(\d+)\.log$")
LOG_PART_RE = re.compile(r"^mcla_(\d+)(\.\d+)?\.log$")


def log_parts(stem):
    """Devuelve las partes de un log en orden cronologico.

    El sink rotatorio del SDK (spdlog) escribe en `mcla_NNN.log` y, al
    llegar a 5 MB, renombra el actual a `mcla_NNN.1.log` y abre uno
    nuevo. El contenido de `.1` es ANTERIOR al de `.log`, asi que un
    crash temprano cae en la parte rotada.

    Leer solo un archivo (el mas reciente) pierde los crashes de las
    primeras vueltas de una ronda larga: es exactamente lo que pasa
    cuando el juego tarda en arrancar y el crash ocurre antes de que
    roten los logs.
    """
    log_dir = ROOT / "out/pc/logs"
    parts = []
    for path in log_dir.glob("mcla_*.log"):
        m = LOG_PART_RE.match(path.name)
        if not m or m.group(1) != stem:
            continue
        # Sin sufijo = 0 (la mas nueva), .1 = 1, .2 = 2...
        index = int(m.group(2)[1:]) if m.group(2) else 0
        parts.append((index, path))
    parts.sort(key=lambda x: -x[0])  # mas antigua primero
    return [path for _, path in parts]


def read_log(stem):
    """Concatena todas las partes de un log en orden cronologico."""
    return "\n".join(p.read_text(errors="replace") for p in log_parts(stem))


def launch(press_script=None, timeout=90):
    """Ejecuta el juego en headless y devuelve (log_stem, fatal_addr).

    Con press_script, el juego recibe pulsaciones de boton (ver
    scripts/test_pad_press.sh): es la unica forma de alcanzar los huecos
    que solo existen en el codigo de input, que el ciclo automatico no
    podia ver porque no pulsaba nada.
    """
    logs = sorted((ROOT / "out/pc/logs").glob("mcla_*.log"))
    before = {p for p in logs}
    cmd = ["./out/pc/mcla",
           f"--game_data_root={GAME_ROOT}",
           f"--user_data_root={ROOT}/out/runtime/user",
           f"--cache_root={ROOT}/out/runtime/cache",
           f"--metadata_root={ROOT}/out/runtime/metadata",
           "--log_level=info", "--headless=true", "--mnk_mode=true",
           "--user_language=1", "--async_shader_compilation=false"]
    env = dict(os.environ)
    if press_script:
        env["MCLA_PAD_PRESS"] = press_script
    try:
        subprocess.run(cmd, cwd=ROOT, timeout=timeout, env=env,
                       capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        pass  # sigue vivo: es una buena señal
    new = [p for p in (ROOT / "out/pc/logs").glob("mcla_*.log") if p not in before]
    if not new:
        return None, None
    # El stem es el numero de la corrida; las partes rotadas comparten stem.
    stems = {LOG_PART_RE.match(p.name).group(1) for p in new
             if LOG_PART_RE.match(p.name)}
    if not stems:
        return None, None
    stem = max(stems, key=lambda s: int(s))
    text = read_log(stem)
    m = FATAL_RE.search(text)
    return stem, (int(m.group(1), 16) if m else None)


def declare(addresses):
    """Anade las direcciones a mcla_analysis.toml bajo [functions]."""
    text = ANALYSIS.read_text()
    if MARKER not in text:
        text = text.rstrip() + f"\n\n{MARKER}\n"
    existing = {int(m, 16) for m in re.findall(r'"0[xX]?([0-9A-Fa-f]{8})"', text)}
    added = [a for a in addresses if a not in existing]
    if not added:
        return []
    for a in added:
        text = text.rstrip() + f'\n"0x{a:08X}" = {{ }}'
    ANALYSIS.write_text(text + "\n")
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rondas", type=int, default=25)
    ap.add_argument("--no-codegen", action="store_true",
                    help="solo análisis, no regenerar")
    ap.add_argument("--pulsar", default=None,
                    help="script de pulsaciones para el juego, "
                         "p.ej. '2:0x1000,8:0x1000'. Sin esto, el ciclo no "
                         "alcanza los huecos que solo existen al pulsar")
    ap.add_argument("--timeout", type=int, default=90,
                    help="segundos de cada ejecucion")
    args = ap.parse_args()

    # El target `mcla` depende del codegen, asi que el build dispara el
    # codegen. Si la validacion falla (ramas huerfanas), el build falla
    # tambien: hay que resolverlo ANTES de compilar, no despues.
    if not args.no_codegen:
        if not regenerate():
            print("  el codegen no pudo converger: parando", flush=True)
            return

    for ronda in range(1, args.max_rondas + 1):
        print(f"\n=== ronda {ronda} ===", flush=True)
        limpiar_shm()
        rebuild()
        stem, addr = launch(press_script=args.pulsar, timeout=args.timeout)
        if addr is None:
            print(f"  log: mcla_{stem}.log", flush=True)
            if stem:
                print(read_log(stem)[-2500:])
            print("  sin crash de funcion no registrada", flush=True)
            return
        print(f"  crash en 0x{addr:08X}", flush=True)
        # El informe de huecos se midio sobre el codigo anterior: tras
        # regenerar, los limites cambian. Releyerlo antes de buscar.
        if not regenerar_huecos():
            print("  no se pudo regenerar el informe de huecos", flush=True)
            return
        gs = gaps()
        gap = next((s for s, size in gs.items() if s <= addr < s + size), None)
        if gap is None:
            print(f"  0x{addr:08X} no cae en ningun hueco conocido", flush=True)
            if stem:
                print(read_log(stem)[-2000:])
            return
        size = gs[gap]
        print(f"  hueco de {size} bytes en 0x{gap:08X}", flush=True)
        # Una entrada cada 8 bytes: un hueco puede contener varias funciones.
        entradas = list(range(gap, gap + size, 8))
        nuevas = declare(entradas)
        print(f"  declaradas {len(nuevas)} entradas: "
              + ", ".join(f"0x{a:08X}" for a in nuevas), flush=True)
        if not nuevas:
            print("  sin progreso: parando", flush=True)
            return
        if not args.no_codegen:
            if not regenerate():
                print("  el codegen no pudo converger: parando", flush=True)
                return


if __name__ == "__main__":
    main()
