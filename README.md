# MCLA 360 → Android (PoC)

Recompilación de **Midnight Club: Los Angeles** (Xbox 360, PowerPC) a ejecutable
nativo, usando [ReXGlue](https://github.com/tynyl/tree/ReXGlue) — el mismo SDK
que usa el port de *Need for Speed: Carbon* de este repositorio.

> **Estado: Proof of Concept.**
>
> - **PC:** el juego arranca, inicializa la emulación de GPU Xenos sobre
>   Vulkan, carga los shaders del menú (256 pipelines gráficos creados) y **se
>   queda vivo** sin errores fatales. La pantalla de título de *Midnight Club:
>   Los Angeles Complete Edition* renderiza con texturas, iluminación y
>   tráfico animado.
> - **PC, con pulsación:** el título **avanza**. El proyecto instala un mando
>   de prueba en el input system del SDK (`src/mcla_scripted_pad.cpp`), así que
>   el PC envía botones como el móvil. Con tres pulsaciones el juego crea 421
>   pipelines frente a 280 del control, **sin un solo error fatal**.
> - **Android:** el juego **corre en el móvil** (Motorola Edge 50 Fusion,
>   Android 16). Llega a la pantalla de título: 292 pipelines gráficos, 0
>   errores fatales, 99.9% de fotogramas sin espera, audio sin silencios y el
>   HUD de FPS encima (2-12 FPS según la escena). APK de release
>   (`com.mcla.android` 0.1.0, arm64-v8a, 21.7 MB) con
>   `scripts/port_android.sh`.
>
> **Lo que falta:** confirmar en el móvil que el título avanza al pulsar, con
> el dispositivo sin uso en primer plano: con otra app delante, Android mata
> el juego por memoria (1.3 GB) y no se puede probar. En el PC eso ya está
> resuelto y comprobado (`scripts/test_pad_press.sh`), pero falta el mismo
> gesto en el táctil real.
>
> Última dirección resuelta: `0x82554080`. Quedan declaradas 76 entradas a
> mano en `mcla_analysis.toml`.

## Qué hay aquí

| Ruta | Qué es |
| --- | --- |
| `mcla_manifest.toml` | Manifiesto del proyecto ReXGlue. Declara la ruta del XEX y qué ficheros de análisis se incluyen. |
| `mcla_analysis.toml` | **Fichero clave.** Declara a mano las direcciones que el análisis automático no puede atribuir a ninguna función. |
| `src/main.cpp`, `src/mcla_app.h` | Punto de entrada de la app y sus hooks de configuración. |
| `src/mcla_scripted_pad.cpp` | Mando de prueba: envía botones al guest en el PC, sin móvil. |
| `scripts/fix_gap_crashes.py` | Ciclo automático que resuelve los huecos de código sin dueño. |
| `scripts/huecos.py` | Localiza los huecos midiendo el C++ generado (viene del SDK). |
| `scripts/test_pad_press.sh` | Prueba la pulsación en el PC y reporta los errores fatales. |
| `scripts/hunt_gaps_with_press.sh` | Cazando los huecos que solo se alcanzan al pulsar. |
| `scripts/ab_test_press.sh` | A/B: ¿las pulsaciones hacen avanzar el juego? |
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

### En Android, el runtime tiene que cargarse con `System.loadLibrary`

El SDK busca el plugin de la GPU por nombre (`dlopen("librexgpu-xenos.so")`).
En Android eso **solo** encuentra una biblioteca que la app ya haya cargado
con `System.loadLibrary`: el `dlopen` de una ruta absoluta no comparte el
namespace del enlazador.

El `SDLActivity` de SDL carga con `System.loadLibrary` lo que devuelve
`getLibraries()`, pero el `libmain.so` del juego lo carga **por ruta**
(`nativeLibraryDir + "/libmain.so"`), en su propio namespace. Por eso el
plugin no se encontraba y el juego se quedaba esperando, sin dibujar.

El arreglo es overridear `getLibraries()` para incluir el runtime:

```java
@Override
protected String[] getLibraries() {
    return new String[]{"SDL3", "rexruntime", "main"};
}
```

Con `librexruntime.so` en el namespace de la app, el `dlopen` del plugin
desde dentro sí lo encuentra. (Es lo que hace el
[fork de GenryTheFox0](https://github.com/GenryTheFox0/rexglue-android).)

### Los contadores de FPS ya están en el SDK

No hace falta cronometrar los fotogramas a mano: el hook de swap del SDK
(`CommandProcessor::ExecutePacketType3_XE_SWAP`) mide el tiempo entre swaps
y lo publica en el registro de contadores con `PROFILE_FRAME_TIME_US()` y
`PROFILE_FPS()`. El launcher solo tiene que leer
`rex::perf::GetSnapshotCounter(kFrameTimeUs)`.

Lo que sí hace falta es **activar los contadores en Release**: el SDK los
compila solo fuera de Release (`add_compile_definitions($<$<NOT:$<CONFIG:
Release>>:REXGLUE_ENABLE_PERF_COUNTERS>)`). El 4º parche los habilita
también en Android, donde el APK es Release.

Un símbolo `weak` definido en el juego tampoco serviría: el hook que mide
los fotogramas vive en el runtime, que se carga en su propio namespace.

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

## Android

El port de Android necesita dos preparativos, porque el SDK compartido
(`nfsmw-android`) tiene su rama Android a medio hacer.

### 1. Parchar el SDK

```bash
python3 scripts/patch_sdk_for_android.py
```

Dos piezas del SDK no pueden enlazar tal cual:

- `src/ui/CMakeLists.txt` enlaza `rex_android_gpu_driver`, un target que
  nadie define → *unable to find library -lrex_android_gpu_driver*.
- `src/ui/vulkan/vulkan_instance.cpp` abre la instancia de Vulkan con un
  cargador propio (`rex_android_open_vulkan`) implementado en
  `android_gpu_driver.cpp`, un archivo que el CMakeLists del SDK no
  compila → *undefined symbol: rex_android_open_vulkan*.

Son el cargador de Vulkan con los hooks del driver de Adreno, que no está en
el checkout. El parche usa el **cargador estándar de Vulkan** del sistema,
como hace el [fork de GenryTheFox0](https://github.com/GenryTheFox0/rexglue-android).

Y una tercera: `thirdparty/CMakeLists.txt` compila SDL3 **estática**, pero el
`SDLActivity` de SDL carga `libSDL3.so` con `System.loadLibrary`. Sin la
compartida, el juego muere al arrancar con *dlopen failed: library
"libSDL3.so" not found*. El parche la compila como compartida en Android.

Se deshace todo con `--revert`.

### 2. Construir el APK

```bash
scripts/port_android.sh          # o --install para instalarlo por adb
scripts/port_android.sh --dry-run   # solo comprueba el toolchain, no compila
```

El script parchea el `CMakeLists.txt` del proyecto con la rama Android
(`add_library SHARED` + `OUTPUT_NAME main`), compila con el NDK, stagea las
librerías en `jniLibs/` y llama a Gradle.

El NDK lo elige **`ndkVersion` de `android/app/build.gradle`**, no "la última
instalada": un NDK distinto al fijado rompe el toolchain de CMake y el error
no menciona el NDK. Si el paquete no está en el SDK, el script lo dice y
manda el comando de `sdkmanager`; con `--ndk` se fuerza otro a propósito
(el script avisa si no coincide con el del proyecto).

El APK sale en `android/app/build/outputs/apk/release/app-release.apk` y no
incluye los datos del juego: el usuario copia su carpeta
(`default.xex`, `*.bik`, `*.rpf`) a `<sdcard>/MCLA`.

### 3. El gamepad táctil

El SDK ya trae la parte difícil: en Android crea un mando sintético
(`is_touch = true`, `synthetic = true` → usuario 0) y publica su estado con
`rex_sdl_set_touch_gamepad_state(botones, lx, ly, rx, ry, lt, rt)`. Los
botones son bits de XInput (`A = 0x1000`, `B = 0x2000`, `X = 0x4000`,
`Y = 0x8000`).

Lo que faltaba era la vista que dibuja el pad y llama a esa función:

- `android/app/src/main/java/com/mcla/android/TouchPadView.java` — el pad
  (sticks, cruceta, A B X Y, LT/RT/LB/RB, L3/R3, BACK/START) y las
  etiquetas de `assets/touchpad.txt`. Se esconde solo si hay un mando real
  conectado.
- `android/app/src/main/cpp/android_touchpad.cpp` — el puente JNI. Va
  dentro de `libmain.so` porque Java solo busca funciones JNI en las
  bibliotecas que cargó él mismo.

Dos cosas que costaron:

- La vista necesita `setClickable(true)`: Android solo entrega los toques
  a una vista que dice que los maneja.
- Al pulsar entraba en el código de input y colgaba en un hueco de la
  tabla de funciones (`0x82554080`, dentro del hueco de 64 bytes que
  empieza en `0x82554060`). Declarado como ocho entradas de 8 bytes. El
  ciclo automático de huecos no lo ve: solo se alcanza al pulsar, y el
  ciclo no pulsa nada.

### 4. Probar la pulsación en el PC

El PC no puede mandar una tecla al juego: el servidor X de esta sesión
rechaza todo evento de teclado sintético (comprobado con `XQueryKeymap`:
ningún keycode mueve el keymap), y el SDL del proyecto es estático, así que
`SDL_PushEvent` desde otro proceso nunca llega a la cola del juego. La
única forma de enviar un botón sin el móvil era el propio móvil.

`src/mcla_scripted_pad.cpp` lo resuelve: es un `rex::input::InputDriver`
que el proyecto instala en el input system del SDK (por la API pública
`InputSystem::AddDriver`, sin tocar el SDK) y que publica un botón XInput
en un temporizador. El dispositivo es sintético, así que el `SlotAssignment`
del SDK lo manda al usuario 0 del guest: **el PC recorre exactamente el
mismo camino de código que el móvil**.

```bash
scripts/test_pad_press.sh                    # una pulsación de A
scripts/test_pad_press.sh "2:0x1000,8:0x1000" # secuencia
```

Los tiempos son relativos a la **primera consulta** del guest al pad, no al
inicio de la ejecución: el juego no mira el mando hasta que llega al título,
unos 35 segundos después de arrancar. Un reloj que arrancase al instalar el
driver dispararía cada pulsación antes de que nadie escuchara.

Con una pulsación de A el título avanza: el juego carga una tanda de
shaders que el control (sin pulsar) nunca carga, y la tanda que ambos
comparten aparece 15 s antes. Con tres pulsaciones seguidas el juego crea
421 pipelines frente a 280 del control, **sin un solo error fatal**: el hueco
`0x82554080` que colgaba al pulsar en el móvil ya no aparece.

Esto además abre el hunting de huecos a los que solo se llega pulsando, que
el ciclo automático no podía ver.

### 5. Cazando los huecos que solo existen al pulsar

El ciclo de `scripts/fix_gap_crashes.py` corre el juego sin tocar nada, así
que nunca veía los huecos del código de input. Con el mando de prueba se
cierran:

```bash
scripts/hunt_gaps_with_press.sh                     # 3 rondas con un guion largo
scripts/fix_gap_crashes.py --pulsar "3:0x1000,7:0x1000"  # una ronda suelta
```

El guion son pares `<segundos>:<máscara XInput>`, y los segundos se cuentan
desde que el guest empieza a mirar el pad. El script es largo y variado a
propósito: **con 16 pulsaciones el juego llega a leer `xarchive_audlo.rpf`,
un archivo que sin pulsaciones no lee nunca** (A/B: 0 lecturas en el
control, 0.3 MB con pulsaciones). Cada pantalla nueva es código nuevo, y el
código nuevo puede tener huecos.

Aviso: esa comparación de `xarchive_audlo.rpf` se hizo con el A/B
defectuoso del que se habla en la sección 7, así que **no es una prueba
válida**. La medida buena es la de la sección 7, con el control que
instala el pad pero no pulsa.

El ciclo también se corrigió por el camino, en dos cosas que lo hacían
perder crashes:

- **Los logs rotan.** El sink del SDK escribe en `mcla_NNN.log` y al llegar
  a 5 MB renombra el actual a `mcla_NNN.1.log`, cuyo contenido es
  **anterior**. El ciclo leía un solo archivo, el más reciente: un crash
  temprano caía en la parte rotada y no se veía. Ahora lee todas las
  partes, en orden cronológico.
- **Una pulsación no es una ventana de tiempo, es una secuencia de
  consultas.** Con una ventana fija de 200 ms, la pulsación se perdía
  cuando el guest estaba ocupado (compilando shaders el polling se
  ralentiza hasta arrastrarse, y la ventana entera cae entre dos
  consultas). Con ocho pulsaciones programadas se entregaban cuatro. Ahora
  la pulsación avanza de consulta en consulta —el botón baja, el guest lo
  ve, el botón sube— así que no se pierde nunca: las ocho se entregan.

### 6. El stick analógico

El guion también mueve los stick, con el prefijo `s:` y los ejes como
`<lx>:<ly>` (izquierdo) o `<lx>:<ly>:<rx>:<ry>` (ambos), cada uno de -1 a 1:

```bash
MCLA_PAD_PRESS="3:s:0:-1,6:0x1000"      # stick abajo, luego A
MCLA_PAD_PRESS="3:s:0:-1:0:0"            # stick abajo
MCLA_PAD_PRESS="3:s:0:-1@6"             # stick abajo 6 segundos
```

Los signos son los de XInput: x positivo es derecha, y positivo es arriba.
El deadzone del SDK es 7849, así que una fracción por encima de 0.25 ya
cuenta como deflection.

A diferencia del botón, el stick no es un flanco sino una posición, y el
guest puede necesitar verlo durante varios frames para mover un cursor.
Por eso se mantiene **6 consultas** en vez de una.

Y el tiempo de sostén se puede pedir con el sufijo `@<segundos>`, que
manda sobre las consultas. Hace falta porque **el juego consulta el pad
unas cuatro veces por segundo**: un sostén medido en consultas es apenas
un segundo, suficiente para mover un cursor de menú y demasiado poco para
girar una rueda. Con el sufijo el stick se mantiene el tiempo pedido
(medido: 6 s pedidos → 3.03 s a 9.02 s, 4 s pedidos → 15.14 s a 19.10 s).

### 7. Lo que de verdad advance el juego

Para medirlo hace falta un **control decente**, y el primero no lo era. El
código hace `if (presses.empty()) return;`, así que sin guion **el pad ni
siquiera se instala** y el guest del control no ve ningún dispositivo de
juego. Ese control comparaba dos cosas a la vez: que hubiera un pad
conectado y que se pulsara algo.

El control justo es un guion que instala el pad pero que nunca dispara: un
gesto programado más allá del final de la corrida (`9999:0x1000`). El guest
ve el mismo dispositivo, pero ningún botón baja. Con `user` y `cache`
limpios antes de cada corrida:

| Corrida | pipelines | gestos | guardado |
|---|---|---|---|
| A: sin pad en absoluto | 556 | 0 | no |
| B: pad presente, no pulsa | 554 | 0 | no |
| C: 16 pulsaciones | 643 | 16 | no |
| D: pad presente, no pulsa | 564 | 0 | no |
| E: 16 pulsaciones | 693 | 16 | no |
| F: stick 4 dir + A + START | 643 | 14 | no |

Lo que dice esto:

- **Tener el pad no cambia nada** (A 556 contra B 554). El avance lo
  causan las pulsaciones, no la presencia del dispositivo.
- **Las pulsaciones sí cambian** (554-564 contra 643-693): del orden de
  100 pipelines más, un 18 %. Es la diferencia entre quedarse en el menú
  y entrar en la partida.
- **El stick rinde igual que los botones** (643 contra 643-693). La
  conclusión anterior de que el stick rendía menos venía del control
  defectuoso, no del stick.

Un `mc4.sav` que aparece es la señal fuerte de que el juego entró en una
partida de verdad, no en un menú. Es intermitente —depende de hasta dónde
llega el juego antes de que acabe la corrida—, así que la medida de
referencia es el conteo de pipelines y el guardado es la confirmación.

Ojo con el conteo absoluto: **es ruidoso**. La misma corrida de control
dio 299, 265 y 556 pipelines en corridas distintas. La diferencia entre
condiciones es sólida, el valor absoluto no sirve para comparar contra
números guardados de otra sesión.

#### La trampa del A/B: el juego necesita un X server

Todo lo anterior costó un rodeo, y vale la pena escribirlo porque el
fallo es **silencioso**. El juego abre una ventana de SDL y sin `DISPLAY`
muere en 0.03 s con `No available video device`. No hay log, no hay crash,
no hay nada: un A/B con ese fallo da **números idénticos siempre** y
parece un resultado. Peor: la primera versión de este A/B comparaba el
log equivocado, porque `mcla_*.log` también matchea `mcla_NNN.1.log`, que
es la parte **rotada** y por tanto **anterior**.

La solución es el driver de video `offscreen` de SDL, que no necesita X:

```bash
./out/pc/mcla ... --video_driver offscreen
```

Con eso el juego corre en un `terminal` sin `DISPLAY`, y el A/B es
fiable. `scripts/test_pad_press.sh` ya lo usa.

### 8. Conducir: el stick tiene que ir DESPUÉS de la intro

Un detalle que cuesta un rodeo entero. El juego mete una cinemática
(`intro720.bik`) entre los menús y la ciudad, y **durante la cinemática el
input no hace nada**: un vídeo no mira el pad.

El juego **sí consulta el pad de forma continua** durante todo el rato
(hasta el poll #1550 a t+239 s), así que el input llega; lo que no llega
es la oportunidad de usarlo. Un stick colocado a t+55 llega al juego,
pero el juego está viendo la intro, así que no pasa nada.

**El problema de fondo: el momento en que el juego llega a la intro varía
entre corridas.** El script de tiempos es un reloj, no un disparador por
evento: un `165:s:1:0@10` significa "en el segundo 165", y si ese segundo
cae dentro de la intro, el stick se pierde. Por eso un guion con el
stick en un tiempo fijo no es fiable:

| Corrida | pipelines | intro | exit |
|---|---|---|---|
| J: entrada, sin stick | 804 | 14 | 124 (completa) |
| J: entrada, sin stick | 930 | 15 | 124 (completa) |
| K: entrada + stick a t+165 | 640 | **0** | 124 (completa) |
| K: entrada + stick a t+165 | 658 | **0** | 124 (completa) |

El stick a t+165 **empeora** el resultado (640-658 contra 804-930) y
además impide que se reproduzca la intro (`bik=0`): el tiempo fijo
empuja al juego a un momento en que el input no sirve para nada.

Ojo con el OOM killer: el juego carga `.rpf` de más de un gigabyte y en
una máquina apretada lo matan. Una corrida muerta da un conteo sin
sentido, así que hay que mirar el código de salida (`124` = llegó al
final, `137` = OOM). Una medición hecha con un control asesinado por el
OOM dio "922 contra 650" y parecía un gran resultado: era una corrida
incompleta comparada contra otra completa.

La solución no es un tiempo mejor elegido, es un **disparador por
evento**: que el stick empiece cuando el juego haya llegado a la intro,
no cuando el reloj diga un número. Los pipelines post-intro son de otro
tipo (vertex shaders `NEDEBENENE`, `NDNBN`, distintos de los de los
menús): es el código de la ciudad, que solo se compila si el juego llega
a la ciudad, y es la señal de que el gameplay se está ejecutando.

## El XEX

El launcher **rechaza** cualquier otro `default.xex`: el código recompilado y
los ganchos dependen de sus direcciones. Esta copia es la verificada:

| | |
| --- | --- |
| Title ID | `545407F8` |
| Media ID | `5940C9DB` |
| Versión | `0.0.0.8` |
| Fecha | 2009-07-17 22:23:19 UTC |
| sha256 (`default.xex`) | `c386f4001fa569e6ad4b982f441f67412f00b3f47c166134555cd4b59854a432` |

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
