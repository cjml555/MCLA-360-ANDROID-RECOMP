# MCLA 360 → Android (PoC)

Recompilación de **Midnight Club: Los Angeles** (Xbox 360, PowerPC) a ejecutable
nativo, usando [ReXGlue](https://github.com/tynyl/tree/ReXGlue) — el mismo SDK
que usa el port de *Need for Speed: Carbon* de este repositorio.

> **Estado: Proof of Concept.** El juego arranca, inicializa la emulación de GPU
> Xenos sobre Vulkan, carga los shaders del menú (50 pipelines gráficos creados)
> y **se queda vivo** sin errores fatales. Aún **no** hay APK para Android:
> falta el proyecto Gradle y portar el arranque del launcher.
>
> Última dirección resuelta: `0x822C9DD8`. Quedan declaradas 68 entradas a
> mano en `mcla_analysis.toml`.

## Qué hay aquí

| Ruta | Qué es |
| --- | --- |
| `mcla_manifest.toml` | Manifiesto del proyecto ReXGlue. Declara la ruta del XEX y qué ficheros de análisis se incluyen. |
| `mcla_analysis.toml` | **Fichero clave.** Declara a mano las direcciones que el análisis automático no puede atribuir a ninguna función. |
| `src/main.cpp`, `src/mcla_app.h` | Punto de entrada de la app y sus hooks de configuración. |
| `scripts/fix_gap_crashes.py` | Ciclo automático que resuelve los huecos de código sin dueño. |
| `scripts/huecos.py` | Localiza los huecos midiendo el C++ generado (viene del SDK). |
| `generated/rexglue.cmake` | Boilerplate del SDK (versionado). El resto de `generated/` se regenera y no se versiona. |

## El problema que resuelve este PoC

El codegen de ReXGlue descubre funciones por análisis del flujo de control.
Eso cubre las llamadas **directas** (`bl`), pero no las **indirectas** (a través
de puntero o vtable). Una función a la que solo se llega de forma indirecta
queda sin dueño, y el juego revienta en tiempo de ejecución con:

```
[FATAL] Call to invalid or unregistered function at guest address 0x827A7FD0
```

El espacio entre el final calculado de una función y el inicio de la siguiente
se llama **hueco**. La herramienta [`tools/huecos.py`](https://github.com/tctechstuff/ReXGlue)
del SDK mide el C++ generado y localiza esos huecos.

El detalle que hace el problema no trivial: **un hueco no es siempre una
función**. Suele contener varias entradas pequeñas seguidas (tablas de thunks
de 8 y 16 bytes). Declarar solo el inicio del hueco hace que el Discover se
lo trague entero, y la siguiente entrada sigue sin quedar registrada: el crash
simplemente **se mueve**.

Por eso `scripts/fix_gap_crashes.py` declara una entrada **cada 8 bytes** dentro
del hueco que ha reventado, en lugar de solo su inicio.

## Cómo funciona el ciclo

```
compila (cmake --build out/pc)
   ↓
ejecuta en headless (--headless=true)
   ↓
lee la dirección que reventó en el log
   ↓
localiza el hueco con tools/huecos.py
   ↓
declara entradas cada 8 bytes en mcla_analysis.toml
   ↓
regenera el codegen (rexglue codegen)   ← ~70 s
   ↓
repite
```

El ciclo se detiene solo cuando el juego deja de reventar con ese error.

## Trampas que costaron tiempo

### Un `SIGBUS` que no era del juego

La arena de memoria del invitado se respalda en `tmpfs`
(`/dev/shm/xenia_memory_*`), **4.8 GB por ejecución**. Varias ejecuciones
seguidas dejan archivos huérfanos y agotan los 5.8 GB de tmpfs. Cuando eso
pasa, el `mmap` del invitado devuelve `SIGBUS` en lugar de `ENOMEM`, y el
crash aparece como *Bus error* dentro de libc, en
`Memory::InitializeFunctionTable` — sin ninguna relación con el código del
juego.

```bash
rm -f /dev/shm/xenia_memory_*     # entre ejecuciones
```

`scripts/fix_gap_crashes.py` lo hace solo antes de cada ronda.

### El plugin de GPU no se carga solo

Sin `config.gpu_plugin = "xenos"` en `OnPreSetup`, el kernel reporta
`no GPU emulation loaded (gpu_plugin not set)` y el juego nunca llega al
menú. El error no es fatal, así que es fácil no verlo entre el ruido del log.

### El codegen se ejecuta dentro del build

El target `mcla` depende del codegen, así que `cmake --build` lo dispara. Si
la validación falla con `UnresolvedCall`, **el build falla también**. Por eso
el codegen va antes de la primera ronda, no después: si no, nunca hay
oportunidad de declarar el destino huérfano.

### Declarar un hueco entero no basta

Un hueco puede contener varias funciones seguidas (tablas de thunks de 8 y
16 bytes). Declarar solo su inicio hace que el Discover se lo trague entero
y las demás entradas siguen sin quedar registradas: **el crash se mueve** a
+8, +24, +64… bytes. La solución es declarar una entrada cada 8 bytes.

### El informe de huecos caduca tras cada regeneración

`scripts/huecos.py` mide el C++ **generado**. En cuanto el codegen reescribe
las funciones, los límites cambian y el informe queda obsoleto. Reléelo
antes de buscar el hueco de la dirección que reventó.

## Requisitos

| Herramienta | Versión |
| --- | --- |
| Clang / LLVM | 20 (probado 20.1.8) |
| CMake | ≥ 3.25 |
| Ninja | reciente |
| Python 3 | con `capstone` 5.0.7 en el *user site* |
| Android SDK | API 35 + NDK `28.2.13676358` (para la fase Android) |
| GPU (PC) | Vulkan 1.1 **con descriptor indexing** |

El SDK compartido (`nfsmw-android/sdk`) debe ser **hermano** de este proyecto
y de la carpeta del juego, porque el manifiesto usa rutas relativas.

## Estructura de carpetas

Debe quedar así:

```
carpeta-de-trabajo/
  MCLA-360-ANDROID-RECOMP/     # este proyecto
  nfsmw-android/               # SDK compartido + renderizador nativo
  midnight-club-la/            # tu copia: default.xex, *.bik, *.rpf
```

El nombre de la carpeta del juego debe coincidir exactamente con `game_root`
del manifiesto, **en minúsculas**. Linux distingue mayúsculas y el fallo
aparece como un `default.xex` "no encontrado" sin más pistas.

## Uso

### 1. Preparar el SDK compartido (una vez)

```bash
cd ../nfsmw-android
python3 tools/fetch_thirdparty.py
```

Es una descarga grande (FFmpeg, SDL3, imgui, tracy, glslang): minutos, no
segundos.

### 2. Generar el código

```bash
./out/pc/rexglue codegen mcla_manifest.toml
```

Tarda ~70 s. Necesita el SDK ya construido
(`cmake --preset linux-amd64` dentro de `nfsmw-android/sdk`).

### 3. Compilar para PC

```bash
cmake -S . -B out/pc -G Ninja \
  -DCMAKE_C_COMPILER=clang-20 -DCMAKE_CXX_COMPILER=clang++-20 \
  -DREXSDK_DIR="$HOME/nfsmw-android/sdk" \
  -DCMAKE_BUILD_TYPE=Release
cmake --build out/pc --target mcla --parallel 4
```

### 4. Ejecutar

```bash
./out/pc/mcla \
  --game_data_root="$HOME/midnight-club-la" \
  --user_data_root="$PWD/out/runtime/user" \
  --cache_root="$PWD/out/runtime/cache" \
  --metadata_root="$PWD/out/runtime/metadata" \
  --log_level=info --headless=true --mnk_mode=true --user_language=1
```

El log va a `out/pc/logs/`.

### 5. Resolver huecos automáticamente

```bash
python3 scripts/fix_gap_crashes.py --max-rondas 40
```

## El XEX

El launcher **rechaza** cualquier otro `default.xex`: el código recompilado y
los ganchos dependen de sus direcciones. Esta copia es la verificada:

| | |
| --- | --- |
| Title ID | `545407F8` |
| Media ID | `5940C9DB` |
| Versión | `0.0.0.8` |
| Fecha | 2009-07-17 22:23:19 UTC |

Si tienes un ISO, **no lo abras con `7z`**: un dump de Xbox 360 usa XDVDFS,
no ISO9660, así que `7z` solo listará la capa DVD-vídeo y terminará con
`Errors: 1` — parece un disco corrupto y no lo es. Usa `extract-xiso`:

```bash
extract-xiso -d ~/<juego> juego.iso
```

## Nota sobre el contenido

Este repositorio **no** incluye el juego. El `default.xex`, los `.bik` y los
`.rpf` los aporta cada usuario desde su propia copia. Solo se versiona el
código fuente de la traducción, los scripts y la configuración del análisis.

## Licencia

MIT. Ver [LICENSE](LICENSE).
