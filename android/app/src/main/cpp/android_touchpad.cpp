// MCLA 360: the on-screen gamepad's bridge to the SDK.
//
// The Java overlay (com.mcla.android.TouchPadView) draws the pad and reads
// the touches; it hands the state here, and the SDK's SDL input driver
// publishes it as the synthetic touch controller, so the game sees an
// ordinary Xbox 360 pad (its menus and button prompts work unchanged).
//
// The feed point is the SDK's own (rex_sdl_set_touch_gamepad_state), the same
// one the NFS Most Wanted port uses: the SDK already creates a synthetic
// controller for it, so no SDL virtual gamepad is needed here and the pad
// works from the first frame.
//
// Compiled into the game's libmain.so: Java looks JNI functions up only in
// the libraries it loaded itself.
//
// SPDX-License-Identifier: GPL-3.0-only

#include <jni.h>

#include <cstdint>

#include <android/log.h>

#include <rex/input/sdl/sdl_input_driver.h>

#define TAG "MCLA-pad"

namespace {

// The view sends the sticks as -1..1, with right and down positive.
int16_t Axis(float v) {
  if (v > 1.0f) v = 1.0f;
  if (v < -1.0f) v = -1.0f;
  return static_cast<int16_t>(v * 32767.0f);
}

// A trigger: the view sends 0..1, XInput wants 0..255.
uint8_t Trigger(float v) {
  if (v <= 0.0f) return 0;
  if (v >= 1.0f) return 255;
  return static_cast<uint8_t>(v * 255.0f + 0.5f);
}

// Releases every button, stick and trigger.
void Release() {
  rex_sdl_set_touch_gamepad_state(0, 0, 0, 0, 0, 0, 0);
}

}  // namespace

// buttons: the XInput button bits (X_INPUT_GAMEPAD_*).
// sticks: -1..1 (the view's convention: down and right positive).
// triggers: 0..1.
extern "C" JNIEXPORT void JNICALL
Java_com_mcla_android_TouchPadView_nativeSetState(JNIEnv*, jclass, jint buttons, jfloat lx, jfloat ly,
                                                    jfloat rx, jfloat ry, jfloat lt, jfloat rt) {
  __android_log_print(ANDROID_LOG_INFO, TAG, "estado botones=0x%x sticks=%f,%f,%f,%f",
                      buttons, lx, ly, rx, ry);
  rex_sdl_set_touch_gamepad_state(
      static_cast<uint16_t>(buttons),
      Axis(lx),
      // XInput's Y axis points up; the view's points down.
      static_cast<int16_t>(-Axis(ly)),
      Axis(rx),
      static_cast<int16_t>(-Axis(ry)),
      Trigger(lt),
      Trigger(rt));
}

// A real controller came or went: the touch pad steps aside so the real one
// is the first player.
//
// There is nothing to attach or detach here: the SDK always has the
// synthetic touch controller. What matters is releasing the state, so a
// button held when a real pad arrives does not stay held behind it.
extern "C" JNIEXPORT jboolean JNICALL
Java_com_mcla_android_TouchPadView_nativeSetActive(JNIEnv*, jclass, jboolean active) {
  Release();
  return JNI_TRUE;
}
