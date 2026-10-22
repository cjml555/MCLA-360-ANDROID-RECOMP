#!/usr/bin/env python3
"""Conduce el juego con un disparador por evento, no por reloj.

El problema: el guion de tiempos es un cronometro, y el juego no lleva el
ritmo del cronometro. El momento en que llega a la cinematica de intro
cambia entre corridas (medido: t+86s a t+101s), asi que un gesto fijado
en un segundo cae unas veces dentro de la intro y otras despues, y una
cinematica ignora el input.

La solucion: que cada gesto espere a su propio fichero-señal, y que este
harness vigile el log del juego y los toque en el orden y con la
separacion que se le pidan. El primer stick se dispara cuando el juego
llega a la intro; los siguientes, a los segundos indicados, a partir de
ese momento. Asi la secuencia es "cuando el juego llego aqui, haz esto,
y luego esto, y luego esto", no "en el segundo 165, haz esto".

Uso:
  python3 scripts/drive_with_trigger.py --timeout 300
  python3 scripts/drive_with_trigger.py --senal intro720.bik --sticks "1:0:10,2:-1:0:10,3:0:-1:10"
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME_ROOT = Path(os.environ.get("MCLA_GAME_ROOT", Path.home() / "midnight-club-la"))
TRIGGER_DIR = Path(os.environ.get("MCLA_TRIGGER_DIR", "/tmp/mcla-triggers"))

# La entrada por los menus, que llega al free roam.
#
# Son EXACTAMENTE 16 gestos, con esta mezcla, y nada mas:
#
#   16 gestos (A, START y D-pad en rotacion)   llega, 2 de 5 corridas
#   16 + cola de mantenimiento de 12            no llega, 0 de 2
#   32 gestos de A PURO                         no llega nunca, 0 de 6
#   48 gestos de la mezcla repetida              no llega, 0 de 2
#
# Dos cosas se han medido:
#
#   - La mezcla importa mas que la cantidad. Pulsar A sin mas es
#     pasarse de opcion: el D-pad y el START son los que mueven los
#     menus.
#   - Anadir mas gestos despues tambien rompe. El guardado se escribe
#     en t+60s, justo cuando el ultimo gesto de los 16 hace su efecto
#     (t+48s). Anyadir una cola de mantenimiento despues deja al
#     juego en un estado donde el menu ya no avanza.
#
# El guardado se crea al entrar en la partida, y ahi es donde el
# trigger engancha: los sticks salen 95s despues, cuando la ciudad ya
# ha cargado (t+155s).
PATRON = ["0x1000", "0x1000", "0x0010", "0x1000", "0x0008",
          "0x1000", "0x0010", "0x1000", "0x0001", "0x1000",
          "0x0010", "0x1000", "0x0008", "0x1000", "0x0010", "0x1000"]
ENTRADA = ",".join(f"{3+i*3}:{PATRON[i]}" for i in range(len(PATRON)))


def log_parts(log_path: Path, launched_at: float = 0.0):
    """Las partes del log en orden cronologico. La '.1.log' es ANTERIOR.

    Ojo: se pasa el PATH del log, no su nombre: las partes se buscan
    como "<nombre sin .log>.log", "<nombre sin .log>.1.log", etc. Si se
    pasa el nombre entero, se buscaria "mcla_099.log.log", que no existe,
    y el log saldria vacio.

    Y con launched_at se descartan las partes anteriores a la corrida:
    un .1.log puede ser de una corrida vieja, con un mc4.sav dentro, y
    el harness lo leeria como si la senal acabara de aparecer. Eso
    hacia que la senal saltase a t+1.7s.
    """
    stem = log_path.name
    if stem.endswith(".log"):
        stem = stem[:-len(".log")]
    ordered = []
    for suffix in (".log", ".1.log", ".2.log", ".3.log"):
        p = log_path.parent / f"{stem}{suffix}"
        if p.exists() and p.stat().st_mtime > launched_at:
            ordered.append(p)
    return ordered


def newest_log(log_dir: Path, newer_than: float = 0.0):
    """El log de la corrida actual.

    No se puede contar ficheros: el sink del SDK renombra el log
    actual a .1.log al llegar a 5 MB, y si ese .1.log ya existe lo
    renombra a .2.log. El numero total de ficheros no crece, asi que
    "hay un log mas que antes" no es una prueba de que la corrida
    actual escribio. Lo que si vale es la marca de tiempo: se cogen
    solo los logs modificados despues de lanzar el juego.
    """
    logs = [p for p in log_dir.glob("mcla_*.log")
            if not re.search(r"\.\d+\.log$", p.name)
            and p.stat().st_mtime > newer_than]
    if not logs:
        return None
    return max(logs, key=lambda p: p.stat().st_mtime)


def parse_sticks(spec: str):
    """"<momento>:<lx>:<ly>[:<rx>:<ry>][@<seg>]" -> lista de gestos.

    El momento es cuantos segundos despues de la senal. El "@<seg>" es
    cuanto se sostiene el stick.
    """
    gestos = []
    for entrada in spec.split(","):
        entrada = entrada.strip()
        if not entrada:
            continue
        momento, _, resto = entrada.partition(":")
        try:
            t = float(momento)
        except ValueError:
            raise SystemExit(f"sticks mal formados: {entrada}")
        hold = 0.0
        if "@" in resto:
            resto, _, hold_text = resto.partition("@")
            try:
                hold = float(hold_text)
            except ValueError:
                raise SystemExit(f"sticks mal formados: {entrada}")
        # El "s:" es opcional: el guion lo acepta, pero aqui se quita
        # para no estorbar al parseo de los ejes.
        if resto.startswith("s:"):
            resto = resto[2:]
        ejes = [float(x) for x in resto.split(":") if x != ""]
        if len(ejes) not in (2, 4):
            raise SystemExit(f"sticks mal formados: {entrada}")
        while len(ejes) < 4:
            ejes.append(0.0)
        accion = "s:%g:%g:%g:%g" % tuple(ejes)
        if hold > 0:
            accion += f"@{hold:g}"
        gestos.append((t, accion))
    return gestos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--senal", default="mc4.sav",
                    help="texto que, al aparecer en el log, dispara el primer stick")
    ap.add_argument("--senal-alt", default="intro720.bik",
                    help="segunda senal que tambien dispara (separada por comas)")
    ap.add_argument("--esperar-save", action="store_true",
                    help="esperar a que aparezca el mc4.sav y NO disparar todavia: "
                         "el save se escribe al entrar, pero la ciudad carga "
                         "despues, y el stick hay que darlo cuando la ciudad "
                         "esta, no cuando se entra")
    ap.add_argument("--sticks",
                    default="5:s:1:0@10,15:s:0:-1@10,25:s:-1:0@10,35:s:0:1@10,45:s:0.5:-0.5@10",
                    help='gestos: "<seg tras la senal>:<lx>:<ly>[:<rx>:<ry>][@<seg>]"')
    ap.add_argument("--retardo", type=float, default=90.0,
                    help="con --esperar-save, segundos tras la senal antes del "
                         "primer stick (la ciudad carga en t+155s y el save "
                         "se escribe en t+60s: unos 90s de diferencia)")
    ap.add_argument("--sin-entrada", action="store_true",
                    help="no hacer la entrada por los menus")
    args = ap.parse_args()

    if not (ROOT / "out/pc/mcla").exists():
        print("ERROR: falta out/pc/mcla", file=sys.stderr)
        return 1
    if not GAME_ROOT.is_dir():
        print(f"ERROR: no esta la copia del juego en {GAME_ROOT}", file=sys.stderr)
        return 1

    gestos = parse_sticks(args.sticks)

    TRIGGER_DIR.mkdir(parents=True, exist_ok=True)
    for stale in TRIGGER_DIR.glob("*"):
        stale.unlink()

    # Un fichero-señal por gesto: cada uno espera al suyo, para que la
    # secuencia tenga su separacion sin depender del reloj del juego.
    senales = []
    for i, (momento, accion) in enumerate(gestos):
        fichero = TRIGGER_DIR / f"paso{i}"
        senales.append((momento, fichero, accion))
        # El timeout de espera es generoso: el juego puede tardar mas de
        # lo que se espera en llegar al punto de la senal, y con
        # --esperar-save el retardo se suma ahi.
        # Las partes se separan con '|': la ruta y la accion tienen
        # dos puntos, asi que con ':' no se podria saber donde acaba
        # una y empieza la otra.
        accion_con_trigger = f"w:{fichero}|600|{accion}"

    # OJO: lo que va al guion es accion_con_trigger, no la accion suelta.
    # La accion suelta no lleva prefijo de tiempo, asi que el parser la
    # rechaza y el gesto no se programa nunca.
    guion = ",".join(
        ([ENTRADA] if not args.sin_entrada else []) +
        [f"w:{f}|600|{a}" for _, f, a in senales]
    )
    env = dict(os.environ)
    env["MCLA_PAD_PRESS"] = guion

    # La arena del invitado va en tmpfs: sin limpiarla, varias ejecuciones
    # seguidas agotan /dev/shm y el fallo aparece como SIGBUS.
    for f in Path("/dev/shm").glob("xenia_memory_*"):
        try:
            f.unlink()
        except OSError:
            pass
    for d in ("user", "cache"):
        target = ROOT / "out/runtime" / d
        subprocess.run(["rm", "-rf", str(target)], check=False)
        target.mkdir(parents=True, exist_ok=True)

    log_dir = ROOT / "out/pc/logs"
    # La marca de tiempo de ahora: solo valen los logs que se escriban a
    # partir de aqui.
    launched_at = time.time()

    print(f"==> {len(gestos)} gestos, disparados por senal")
    for momento, fichero, accion in senales:
        print(f"      t+{momento:>5}s tras la senal  ->  {accion}")
    print(f"==> esperando la senal '{args.senal}' en el log (timeout {args.timeout}s)")

    started = time.time()
    proc = subprocess.Popen(
        ["./out/pc/mcla",
         f"--game_data_root={GAME_ROOT}",
         f"--user_data_root={ROOT}/out/runtime/user",
         f"--cache_root={ROOT}/out/runtime/cache",
         f"--metadata_root={ROOT}/out/runtime/metadata",
         "--log_level=info", "--headless=true", "--mnk_mode=true",
         "--user_language=1", "--video_driver=offscreen"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    senal_vista = None
    senal_nombre = None
    proximo = 0
    try:
        while time.time() - started < args.timeout:
            if proc.poll() is not None:
                print(f"==> el juego termino antes de tiempo (codigo {proc.returncode})")
                break
            ahora = time.time() - started
            log = newest_log(log_dir, launched_at)
            if log:
                try:
                    text = "\n".join(
                        p.read_text(encoding="utf-8", errors="replace")
                        for p in log_parts(log, launched_at)
                    )
                except OSError:
                    text = ""
                # El juego es NO DETERMINISTA: la misma entrada de 16
                # gestos unas veces llega a crear el guardado y otras no
                # (medido: misma entrada, con save t+60s en una corrida y
                # sin save en otra). Por eso se aceptan varias senales:
                # dispara la que aparezca primero.
                senales_texto = [s for s in (args.senal, args.senal_alt) if s]
                vista = next((s for s in senales_texto if s in text), None)
                if vista and not senal_vista:
                    senal_vista = ahora
                    senal_nombre = vista
                    print(f"==> senal '{vista}' vista en t+{senal_vista:.1f}s")
                    if args.esperar_save:
                        # El save se escribe al ENTRAR, pero la ciudad
                        # carga despues (t+155s). El stick hay que darlo
                        # con la ciudad ya dentro, asi que la senal solo
                        # marca el momento: los sticks esperan su turno.
                        print("    (esperando: la ciudad carga despues del save)")
            if senal_vista is not None and proximo < len(senales):
                # Con --esperar-save, los sticks no salen hasta pasado
                # el retardo, que es cuando la ciudad ya esta.
                espera = args.retardo if args.esperar_save else 0.0
                momento, fichero, _ = senales[proximo]
                if ahora - senal_vista >= momento + espera:
                    fichero.touch()
                    print(f"==> t+{ahora - senal_vista:.1f}s tras la senal: disparo {proximo}")
                    proximo += 1
            time.sleep(0.25)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    log = newest_log(log_dir, launched_at)
    if not log:
        print("ERROR: no hay log de esta corrida")
        return 1
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in log_parts(log, launched_at))
    pipes = text.count("Creating graphics pipeline")
    fatal = text.count("invalid or unregistered")
    bik = text.count(args.senal)
    saves = list((ROOT / "out/runtime/user").rglob("*.sav"))

    print()
    print("==> resultado")
    print(f"    pipelines:          {pipes}")
    print(f"    errores fatales:    {fatal}")
    print(f"    lecturas de intro:  {bik}")
    print(f"    disparos:           {text.count('trigger fired')}")
    print(f"    partida guardada:   {'si' if saves else 'no'}")
    if senal_vista is not None:
        print(f"    senal a los:        t+{senal_vista:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
