#!/usr/bin/env python3
"""Buscar el guion que llega al free roam de forma fiable.

Lo que se ha medido:

  corrida 100 (llego):  12 tandas, pico de 128 pipelines en t+155s
  corrida 102 (no llego): 6 tandas, se detiene en t+57s

Los 16 gestos de la entrada terminan en t+62s, pero la ciudad carga en
t+155s: el input se acaba antes de que el juego este listo. La entrada
tiene que durar mas, y repartir los gestos mas.

Este script prueba guiones de entrada distintos, cada uno en una corrida
limpia, y dice cuantos llegaron (el guardado mc4.sav es la senal) y
cuantos pipelines creo cada uno.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME_ROOT = Path(os.environ.get("MCLA_GAME_ROOT", Path.home() / "midnight-club-la"))
LOG_DIR = ROOT / "out/pc/logs"

# Los botones que se usan: A, START y el D-pad.
A, START, DPAD = "0x1000", "0x0010", "0x0008"


def entrada(guiones):
    return ",".join(guiones)


def correr(nombre, guion, timeout=300):
    for f in Path("/dev/shm").glob("xenia_memory_*"):
        try:
            f.unlink()
        except OSError:
            pass
    for d in ("user", "cache"):
        t = ROOT / "out/runtime" / d
        shutil.rmtree(t, ignore_errors=True)
        t.mkdir(parents=True, exist_ok=True)

    launched = time.time()
    env = dict(os.environ)
    env["MCLA_PAD_PRESS"] = guion
    try:
        subprocess.run(
            ["./out/pc/mcla",
             f"--game_data_root={GAME_ROOT}",
             f"--user_data_root={ROOT}/out/runtime/user",
             f"--cache_root={ROOT}/out/runtime/cache",
             f"--metadata_root={ROOT}/out/runtime/metadata",
             "--log_level=info", "--headless=true", "--mnk_mode=true",
             "--user_language=1", "--video_driver=offscreen"],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        pass

    logs = [p for p in LOG_DIR.glob("mcla_*.log")
            if not re.search(r"\.\d+\.log$", p.name)
            and p.stat().st_mtime > launched]
    if not logs:
        print(f"  {nombre:38s} SIN LOG")
        return None
    log = max(logs, key=lambda p: p.stat().st_mtime)
    stem = log.name[:-4] if log.name.endswith(".log") else log.name
    parts = []
    for suffix in (".log", ".1.log", ".2.log", ".3.log"):
        p = LOG_DIR / f"{stem}{suffix}"
        if p.exists():
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
    text = "\n".join(parts)

    pipes = text.count("Creating graphics pipeline")
    save = "mc4.sav" in text
    bik = text.count("intro720.bik")
    # Cuando se creo el guardado: el momento en que el juego llego.
    m = re.search(r"crear .mc4\.sav", text)
    t_save = ""
    if m:
        ts = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text[:m.start()])
        if ts:
            t0 = re.search(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
            if t0:
                import datetime
                f = "%Y-%m-%d %H:%M:%S"
                d = (datetime.datetime.strptime(ts.group(1), f)
                     - datetime.datetime.strptime(t0.group(1), f)).total_seconds()
                t_save = f"t+{int(d)}s"
    print(f"  {nombre:38s} pipes={pipes:4d} save={'SI' if save else 'no':3s} "
          f"({t_save:8s}) intro={bik}")
    return {"pipes": pipes, "save": save, "bik": bik}


def main():
    if not (ROOT / "out/pc/mcla").exists():
        print("ERROR: falta out/pc/mcla", file=sys.stderr)
        return 1

    # Los candidatos: la entrada original (16 gestos, hasta t+48) y
    # variantes que llegan mas lejos.
    base16 = [f"{3+i*3}:{A}" for i in range(16)]
    candidatos = {
        "16 gestos, hasta t+48 (el de antes)": ",".join(base16),
        "24 gestos, hasta t+72": ",".join(f"{3+i*3}:{A}" for i in range(24)),
        "24 gestos, hasta t+90 (cada 4s)": ",".join(f"{3+i*4}:{A}" for i in range(24)),
        "32 gestos, hasta t+126 (cada 4s)": ",".join(f"{3+i*4}:{A}" for i in range(32)),
        "16 A + 16 START intercalados": ",".join(
            f"{3+i*6}:{A},{6+i*6}:{START}" for i in range(16)),
        "20 A + D-pad, cada 4s, hasta t+96": ",".join(
            f"{3+i*4}:{A},{5+i*4}:{DPAD}" for i in range(20)),
    }

    print("==> buscando el guion de entrada que llega al free roam")
    for nombre, guion in candidatos.items():
        correr(nombre, guion)

    print()
    print("La senal de llegada es el mc4.sav: el juego lo escribe cuando entra")
    print("en la partida. Los pipelines de mas son codigo de la ciudad.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
