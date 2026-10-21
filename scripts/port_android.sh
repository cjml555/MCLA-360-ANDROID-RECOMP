#!/usr/bin/env bash
# Compila MCLA para Android y produce el APK.
#
# Es el equivalente en bash del port.ps1 del fork GenryTheFox0/rexglue-android
# (aquel esta en PowerShell y asume Windows). Hace lo mismo:
#
#   1. Parchea el CMakeLists.txt del proyecto con la rama Android
#      (add_library SHARED + OUTPUT_NAME main), si no esta ya.
#   2. Configura y compila el juego con el toolchain del NDK.
#   3. Stagea las librerias nativas en el proyecto Gradle.
#   4. Compila el APK con Gradle.
#
# Uso:
#   scripts/port_android.sh [--sdk <android-sdk>] [--ndk <ndk>] [--jobs N]
#                            [--abi arm64-v8a] [--install] [--dry-run]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/sdk}}"
NDK=""
JOBS="$(nproc 2>/dev/null || echo 4)"
ABI="arm64-v8a"
INSTALL=0
DRY_RUN=0
REXSDK_DIR="$ROOT/../nfsmw-android/sdk"

while [ $# -gt 0 ]; do
  case "$1" in
    --sdk) SDK="$2"; shift 2 ;;
    --ndk) NDK="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --abi) ABI="$2"; shift 2 ;;
    --install) INSTALL=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "opcion desconocida: $1" >&2; exit 1 ;;
  esac
done

say() { printf '\033[36m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# ---- herramientas
[ -d "$SDK" ] || fail "Android SDK no encontrado en $SDK (usa --sdk)"

# La version del NDK la fija el proyecto: ndkVersion en android/app/build.gradle.
# NO se elige "la mas nueva instalada": un NDK distinto al fijado rompe el
# build (toolchain, libc++ y el ABI de las libs nativas), y el error sale
# como un fallo de CMake que no menciona el NDK.
REQUIRED_NDK="$(sed -n "s/.*ndkVersion[[:space:]]*'\([^']*\)'.*/\1/p" \
  "$ROOT/android/app/build.gradle" 2>/dev/null | head -1)"

if [ -z "$NDK" ]; then
  if [ -n "$REQUIRED_NDK" ]; then
    NDK="$SDK/ndk/$REQUIRED_NDK"
    [ -d "$NDK" ] || fail "el proyecto pide el NDK $REQUIRED_NDK (ndkVersion en android/app/build.gradle) y no esta en $SDK/ndk.
  Instalalo con: sdkmanager \"ndk;$REQUIRED_NDK\"
  O usa --ndk <ruta> para forzar otro."
  else
    # Sin ndkVersion declarado: se cae a la mas nueva instalada.
    NDK=$(ls -d "$SDK"/ndk/*/ 2>/dev/null | sort -V | tail -1 || true)
    NDK="${NDK%/}"
  fi
fi
[ -n "$NDK" ] && [ -d "$NDK" ] || fail "NDK no encontrado (usa --ndk)"

# Un NDK a medias (sin source.properties) rompe el toolchain de CMake.
[ -f "$NDK/source.properties" ] || fail "el NDK $NDK no tiene source.properties: instalacion incompleta, reinstala el paquete"
if [ -n "$REQUIRED_NDK" ]; then
  PKG_REV="$(sed -n 's/^Pkg\.Revision[[:space:]]*=[[:space:]]*//p' "$NDK/source.properties" | tr -d '\r')"
  [ "$PKG_REV" = "$REQUIRED_NDK" ] || say "AVISO: el NDK elegido es $PKG_REV y el proyecto pide $REQUIRED_NDK"
fi

CMAKE="$SDK/cmake/3.31.6/bin/cmake"
[ -x "$CMAKE" ] || CMAKE="$(command -v cmake || true)"
[ -n "$CMAKE" ] || fail "cmake no encontrado"
NINJA="$SDK/cmake/3.31.6/bin/ninja"
[ -x "$NINJA" ] || NINJA="$(command -v ninja || true)"

TOOLCHAIN="$NDK/build/cmake/android.toolchain.cmake"
[ -f "$TOOLCHAIN" ] || fail "toolchain del NDK no encontrado: $TOOLCHAIN"
LLVM_BIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin"
[ -d "$LLVM_BIN" ] || fail "binarios LLVM del NDK no encontrados"

say "SDK:   $SDK"
say "NDK:   $NDK"
say "ABI:   $ABI  ($JOBS hilos)"

if [ "$DRY_RUN" = 1 ]; then
  say "dry-run: se para aqui, no se compila nada"
  exit 0
fi

# ---- 1. rama Android en el CMakeLists.txt del proyecto
LISTS="$ROOT/CMakeLists.txt"
[ -f "$LISTS" ] || fail "no hay CMakeLists.txt en el proyecto"
if ! grep -q 'if\s*(\s*ANDROID\s*)' "$LISTS"; then
  [ -f "$LISTS.bak" ] || cp "$LISTS" "$LISTS.bak"
  say "añadiendo la rama Android al CMakeLists.txt"
  python3 - "$LISTS" <<'PY'
import re, sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
pat = re.compile(r'(?m)^if\(WIN32\)(\r?\n)([ \t]*)add_executable\((\S+) WIN32 (\$\{\w+\})\)')
m = pat.search(text)
if not m:
    sys.exit("no se encontro el add_executable estandar; añade la rama Android a mano")
nl, ind, target, src = m.group(1), m.group(2), m.group(3), m.group(4)
repl = (f"if(ANDROID){nl}{ind}# Android: el juego es libmain.so, que carga la actividad de SDL3.{nl}"
        f"{ind}add_library({target} SHARED {src}){nl}"
        f"{ind}set_target_properties({target} PROPERTIES OUTPUT_NAME main){nl}"
        f"elseif(WIN32){nl}{ind}add_executable({target} WIN32 {src})")
open(path, "w", encoding="utf-8").write(pat.sub(lambda _: repl, text, count=1))
PY
else
  say "la rama Android ya esta en CMakeLists.txt"
fi

# ---- 2. configurar y compilar el juego
BUILD="$ROOT/out/android-$ABI"
say "configurando ($ABI)"
mkdir -p "$BUILD" "$ROOT/out/tmp"
TMPDIR="$ROOT/out/tmp" "$CMAKE" -S "$ROOT" -B "$BUILD" -G Ninja \
  "-DCMAKE_MAKE_PROGRAM=$NINJA" \
  "-DCMAKE_TOOLCHAIN_FILE=$TOOLCHAIN" \
  "-DANDROID_ABI=$ABI" \
  -DANDROID_PLATFORM=android-26 \
  -DANDROID_STL=c++_shared \
  -DCMAKE_BUILD_TYPE=Release \
  "-DREXSDK_DIR=$REXSDK_DIR" \
  -DREXGLUE_USE_VULKAN=ON \
  -DREXGLUE_USE_D3D12=OFF \
  -DREXGLUE_BUILD_TESTS=OFF \
  -DREXGLUE_ENABLE_TRACY=OFF \
  -DPYTHON_EXECUTABLE="$(command -v python3)" \
  -DPython3_EXECUTABLE="$(command -v python3)"

say "compilando ($ABI) - la primera vez tarda"
TMPDIR="$ROOT/out/tmp" "$CMAKE" --build "$BUILD" --parallel "$JOBS"

# ---- 3. stagear las librerias
MAIN=$(find "$BUILD" -name 'libmain.so' | head -1)
[ -n "$MAIN" ] || fail "la compilacion termino pero no hay libmain.so"
LIBS_DIR="$ROOT/android/app/src/main/jniLibs/$ABI"
say "stageando las librerias en $LIBS_DIR"
rm -rf "$LIBS_DIR"; mkdir -p "$LIBS_DIR"

stage() { # <origen> <nombre>
  [ -f "$1" ] || return 0
  "$LLVM_BIN/llvm-strip" --strip-debug -o "$LIBS_DIR/$2" "$1"
  say "  $2"
}
stage "$MAIN" libmain.so

# El runtime y los plugins de GPU salen junto al ejecutable.
for so in "$BUILD"/librex*.so "$BUILD"/**/librex*.so; do
  [ -f "$so" ] || continue
  stage "$so" "$(basename "$so")"
done
# El runtime tambien puede estar en la salida del SDK.
for so in "$REXSDK_DIR"/out/android-arm64/librex*.so "$REXSDK_DIR"/out/android-arm64/*/librex*.so; do
  [ -f "$so" ] || continue
  stage "$so" "$(basename "$so")"
done
[ -f "$LIBS_DIR/librexruntime.so" ] || fail "no se encontro librexruntime.so"

case "$ABI" in
  arm64-v8a) TRIPLE=aarch64-linux-android ;;
  x86_64)   TRIPLE=x86_64-linux-android ;;
esac
stage "$LLVM_BIN/../sysroot/usr/lib/$TRIPLE/libc++_shared.so" libc++_shared.so

say "librerias en el APK:"
ls -1 "$LIBS_DIR" | sed 's/^/  /'

# ---- 4. el APK
say "compilando el APK"
cd "$ROOT/android"
ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK" \
  ./gradlew assembleRelease -PrexSdkDir="$REXSDK_DIR" --no-daemon

APK="$ROOT/android/app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || fail "no se genero el APK"
say "APK: $APK"
ls -la "$APK" | sed 's/^/  /'

if [ "$INSTALL" = 1 ]; then
  command -v adb >/dev/null || fail "adb no encontrado (instala platform-tools)"
  say "instalando"
  adb install -r "$APK"
fi
