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
"""

import argparse
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


def gaps():
    """Devuelve {start: size} de los huecos >= 8 bytes leidos del informe."""
    report = Path("/tmp/huecos_mcla.txt")
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


def regenerate():
    print("  * regenerando codegen (~70s)...", flush=True)
    r = run(["./out/pc/rexglue", "codegen", "mcla_manifest.toml"], cwd=ROOT, timeout=900)
    if r.returncode != 0:
        print(r.stdout[-4000:])
        print(r.stderr[-2000:])
        raise SystemExit("fallo el codegen")
    m = re.search(r"Codegen summary: (\d+) written, (\d+) unchanged", r.stdout)
    print(f"  * codegen: {m.group(0) if m else 'ok'}", flush=True)
    if "Validation failed" in r.stdout or "unresolved calls" in r.stdout:
        raise SystemExit("validacion fallida: " + r.stdout[-1500:])


def launch():
    """Ejecuta el juego en headless y devuelve (log_path, fatal_addr)."""
    logs = sorted((ROOT / "out/pc/logs").glob("mcla_*.log"))
    before = {p for p in logs}
    cmd = ["./out/pc/mcla",
           f"--game_data_root={GAME_ROOT}",
           f"--user_data_root={ROOT}/out/runtime/user",
           f"--cache_root={ROOT}/out/runtime/cache",
           f"--metadata_root={ROOT}/out/runtime/metadata",
           "--log_level=info", "--headless=true", "--mnk_mode=true",
           "--user_language=1", "--async_shader_compilation=false"]
    try:
        run(cmd, cwd=ROOT, timeout=60)
    except subprocess.TimeoutExpired:
        pass  # sigue vivo: es una buena señal
    new = [p for p in (ROOT / "out/pc/logs").glob("mcla_*.log") if p not in before]
    if not new:
        return None, None
    log = max(new, key=lambda p: p.stat().st_mtime)
    text = log.read_text(errors="replace")
    m = FATAL_RE.search(text)
    return log, (int(m.group(1), 16) if m else None)


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
    args = ap.parse_args()

    for ronda in range(1, args.max_rondas + 1):
        print(f"\n=== ronda {ronda} ===", flush=True)
        rebuild()
        log, addr = launch()
        if addr is None:
            print(f"  log: {log}", flush=True)
            if log:
                print(log.read_text(errors='replace')[-2500:])
            print("  sin crash de funcion no registrada", flush=True)
            return
        print(f"  crash en 0x{addr:08X}", flush=True)
        gs = gaps()
        gap = next((s for s, size in gs.items() if s <= addr < s + size), None)
        if gap is None:
            print(f"  0x{addr:08X} no cae en ningun hueco conocido", flush=True)
            if log:
                print(log.read_text(errors='replace')[-2000:])
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
            regenerate()


if __name__ == "__main__":
    main()
