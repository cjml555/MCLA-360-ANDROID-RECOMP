# Evaluación: usar el fork GenryTheFox0/rexglue-android

**Fecha:** 2026-10-20
**Repositorio:** https://github.com/GenryTheFox0/rexglue-android (rama `android`)
**Commit:** `2026-10-19 14:44:50 +0300`

## Veredicto

**Adoptar el fork como SDK de Android**, por encima de seguir parcheando
`nfsmw-android` a mano. Reasons:

1. El codegen es **idéntico** (`phase_gapfill.cpp`, `function_graph.cpp`,
   `analyze.cpp` byte a byte), así que las 68 declaraciones de
   `mcla_analysis.toml` siguen siendo válidas.
2. Resuelve el **input del juego**, que es un bloqueo real: el
   `android_touchpad.cpp` del SDK crea un **joystick virtual SDL** y el juego
   ve un mando Xbox normal. Sin esto, el juego no se puede jugar (el
   servidor X de esta sesión además solo acepta XTEST para 3 keycodes).
3. Trae la **capa Android completa**: `port.ps1` (parchea el CMakeLists del
   juego, compila con NDK, stagea las librerías, arma y firma el APK) y un
   `template/` con launcher, instalación del juego desde una carpeta y
   gamepad táctil completo (stick, D-pad, ABXY, gatillos, shoulders).
4. Usa **Vulkan estándar** con `VK_KHR_android_surface`, sin el driver
   propietario de Adreno: menos código, menos superficie de fallo.

## Lo que el fork NO tiene (y hay que resolver)

| Falta | Impacto | Plan |
| --- | --- | --- |
| `rex_android_gpu_driver` | **Alta**: es un enlace roto en `nfsmw-android/sdk/src/ui/CMakeLists.txt:184` a un target que nadie define. Bloquea el link de `librexruntime.so`. | El fork no lo tiene: usa Vulkan estándar. adopted. |
| `port.ps1` es PowerShell | Media: aquí no hay `pwsh` y el path del SDK es Linux. | Portar la lógica a `scripts/port_android.sh` (los pasos son 6 y están bien identificados). |
| `thirdparty/` vacío | Baja: son submódulos de git. | `git submodule update --init --recursive` en el fork. |
| `reeot` (Spider-Man) | Ninguno para MCLA. | Es otro repo. |

## Diferencias con `nfsmw-android` (nuestro SDK actual)

- Nuestro SDK: 612 archivos `.cpp/.h`; el fork: 592.
- El fork es **más nuevo** (19 oct vs 8 oct) y está basado en el upstream de
  ReXGlue, no en nuestro parche.
- Nuestro SDK tiene parches locales de Android que el fork no trae
  (`writable_executable_memory`, el driver de Adreno). El fork es **más
  simple**, no más pobre: lo que sí tiene, funciona.

## Migración

1. Clonar el fork como hermano de `MCLA-360-ANDROID-RECOMP`:
   `~/rexglue-android/`
2. Copiar `android/template/` al proyecto como base del launcher.
3. Portar `port.ps1` a bash: `cmake -S <proyecto> -B out/android-arm64`
   con el toolchain del NDK, stage de `libmain.so` + `librex*.so` +
   `libc++_shared.so` a `jniLibs/`, y `assembleRelease` de Gradle.
4. El `CMakeLists.txt` del proyecto necesita la rama Android
   (`add_library(mcla SHARED ...)` + `OUTPUT_NAME main`), que este repo ya
   tiene.
5. `mcla_analysis.toml` se queda igual: el codegen es el mismo.

## Nota sobre el input

El fork resuelve el input de forma nativa con un joystick virtual SDL, así
que **no** depende de XTEST ni de remapear keybinds. En el PC, en cambio, el
input por teclado sigue siendo incómodo en esta sesión: el servidor X solo
acepta `XTestFakeButtonEvent` para los keycodes 8, 9 y 10, y el SDL del
proyecto es estático, así que `SDL_PushEvent` desde otro proceso no llega a
la misma cola.
