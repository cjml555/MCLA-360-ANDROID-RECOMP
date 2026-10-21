#!/usr/bin/env python3
"""Parchea el SDK para Android: quita el enlace a un target que no existe.

El SDK (nfsmw-android) tiene en src/ui/CMakeLists.txt, en su rama ANDROID:

    target_link_libraries(rexui PRIVATE android rex_android_gpu_driver)

Ese target no lo define nadie en el checkout: el enlazado de
librexruntime.so falla con "unable to find library -lrex_android_gpu_driver".
El plugin Xenos ya habla Vulkan con VK_KHR_android_surface, asi que el driver
de stock no hace falta: se cambia por "log", que si existe en el NDK.

El parche se aplica al checkout del SDK (no al proyecto), como hace el port de
Carbon con el suyo. Es idempotente.

Uso:
    python3 scripts/patch_sdk_for_android.py [--sdk <ruta>] [--revert]
"""

import argparse
import re
import sys
from pathlib import Path

BROKEN = "    target_link_libraries(rexui PRIVATE android rex_android_gpu_driver)"
FIXED = "    target_link_libraries(rexui PRIVATE android log)"


def patch_file(path, broken, fixed, label):
    """Sustituye 'broken' por 'fixed'. Devuelve True si cambio algo."""
    if not path.is_file():
        print(f"  {label}: no existe")
        return False
    text = path.read_text(encoding="utf-8")
    if fixed in text and broken not in text:
        print(f"  {label}: ya parcheado")
        return False
    if broken not in text:
        print(f"  {label}: no encontrado (el SDK quiza cambio; revisa)")
        return False
    path.write_text(text.replace(broken, fixed, 1), encoding="utf-8")
    print(f"  {label}: parcheado")
    return True


def unpatch_file(path, broken, fixed, label):
    """Deshace patch_file. Devuelve True si cambio algo."""
    if not path.is_file():
        print(f"  {label}: no existe")
        return False
    text = path.read_text(encoding="utf-8")
    if fixed not in text:
        print(f"  {label}: no habia parche que deshacer")
        return False
    path.write_text(text.replace(fixed, broken, 1), encoding="utf-8")
    print(f"  {label}: deshecho")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", default=None,
                    help="ruta del SDK (por defecto ../nfsmw-android/sdk)")
    ap.add_argument("--revert", action="store_true",
                    help="deshace el parche")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    sdk = Path(args.sdk) if args.sdk else root.parent / "nfsmw-android" / "sdk"
    if not sdk.is_dir():
        sys.exit(f"no existe el SDK en {sdk}")

    print(f"SDK: {sdk}")
    if args.revert:
        unpatch_file(sdk / "src" / "ui" / "CMakeLists.txt",
                     BROKEN, FIXED, "src/ui/CMakeLists.txt")
        patch_vulkan_loader(sdk, True)
        return 0

    changed = False
    changed |= patch_file(sdk / "src" / "ui" / "CMakeLists.txt",
                         BROKEN, FIXED, "src/ui/CMakeLists.txt")
    patch_vulkan_loader(sdk, False)
    if not changed:
        print("no habia nada que parchear")
    return 0


# --- 2. el cargador de Vulkan propio -------------------------------------
#
# vulkan_instance.cpp abre la instancia con un cargador propio en Android:
#
#     vulkan_instance->loader_.Adopt(rex_android_open_vulkan(...));
#
# Ese simbolo lo implementa src/ui/vulkan/android_gpu_driver.cpp, un archivo
# que el CMakeLists del SDK no incluye en ninguna lista de fuentes: no se
# compila nunca, y el enlazado de librexruntime.so falla con
# "undefined symbol: rex_android_open_vulkan".
#
# El arreglo es usar el cargador estandar de Vulkan del sistema, que es lo
# que hace el fork GenryTheFox0/rexglue-android. El plugin Xenos ya pide
# VK_KHR_android_surface, asi que el juego dibuja igual; lo unico que se
# pierde es la posibilidad de forzar un driver de Adreno especifico, que
# tampoco esta disponible.

BROKEN_LOADER = """#if REX_PLATFORM_ANDROID
  vulkan_instance->loader_.Adopt(rex_android_open_vulkan(
      REXCVAR_GET(android_native_lib_dir).c_str(), REXCVAR_GET(android_tmp_dir).c_str(),
      REXCVAR_GET(android_gpu_driver_dir).c_str(), REXCVAR_GET(android_gpu_driver_name).c_str()));
  loader_loaded = bool(vulkan_instance->loader_);
  REXLOG_INFO("Vulkan requested driver: {}", REXCVAR_GET(android_gpu_driver_name).empty()
      ? "system" : REXCVAR_GET(android_gpu_driver_name));
#else
  loader_loaded = vulkan_instance->loader_.Load(platform::lib_names::kVulkanLoader);
#endif"""

FIXED_LOADER = """#if REX_PLATFORM_ANDROID
  // The stock Vulkan loader of the system. The custom Adreno loader
  // (rex_android_open_vulkan) lives in a driver that is not part of this
  // checkout, so it can not be used here.
  loader_loaded = vulkan_instance->loader_.Load(platform::lib_names::kVulkanLoader);
  REXLOG_INFO("Vulkan loader: the system one");
#else
  loader_loaded = vulkan_instance->loader_.Load(platform::lib_names::kVulkanLoader);
#endif"""


def patch_vulkan_loader(sdk, revert):
    target = sdk / "src" / "ui" / "vulkan" / "vulkan_instance.cpp"
    if not target.is_file():
        print(f"  vulkan_instance.cpp: no existe")
        return
    text = target.read_text(encoding="utf-8")
    if revert:
        if FIXED_LOADER in text:
            target.write_text(text.replace(FIXED_LOADER, BROKEN_LOADER, 1), encoding="utf-8")
            print("  vulkan_instance.cpp: cargador propio restaurado")
        else:
            print("  vulkan_instance.cpp: no habia parche que deshacer")
        return
    if FIXED_LOADER in text and BROKEN_LOADER not in text:
        print("  vulkan_instance.cpp: ya parcheado")
        return
    if BROKEN_LOADER not in text:
        print("  vulkan_instance.cpp: el bloque no coincide (el SDK quiza cambio)")
        return
    target.write_text(text.replace(BROKEN_LOADER, FIXED_LOADER, 1), encoding="utf-8")
    print("  vulkan_instance.cpp: se usa el cargador estandar de Vulkan")


if __name__ == "__main__":
    sys.exit(main())
