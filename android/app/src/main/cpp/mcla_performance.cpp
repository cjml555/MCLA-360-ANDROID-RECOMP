// MCLA 360: the launcher's performance readouts.
//
// The SDK already times the frames: the swap hook (ExecutePacketType3_XE_SWAP)
// measures the time between swaps and publishes it in the perf registry
// (rex::perf::CounterId::kFrameTimeUs and kFps). The launcher only has to
// read it and, optionally, point the registry at a CSV file.
//
// The counters are compiled out in Release by default; the SDK patch for
// Android turns them on there (see scripts/patch_sdk_for_android.py).
//
// SPDX-License-Identifier: BSD-3-Clause

#include <jni.h>

#include <cstdint>
#include <string>

#include <rex/logging.h>
#include <rex/perf/counter.h>

extern "C" JNIEXPORT jlong JNICALL
Java_com_mcla_android_GameActivity_nativeFrameTimeUs(JNIEnv*, jclass) {
  // The time of a frame in microseconds. Zero means "no frame yet" (still
  // loading): the launcher shows a dash then.
#ifdef REXGLUE_ENABLE_PERF_COUNTERS
  return rex::perf::GetSnapshotCounter(rex::perf::CounterId::kFrameTimeUs);
#else
  return 0;
#endif
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_mcla_android_GameActivity_nativeFramesPresented(JNIEnv*, jclass) {
  // The frames per second the SDK measured.
#ifdef REXGLUE_ENABLE_PERF_COUNTERS
  return rex::perf::GetSnapshotCounter(rex::perf::CounterId::kFps);
#else
  return 0;
#endif
}

extern "C" JNIEXPORT void JNICALL
Java_com_mcla_android_GameActivity_nativeStartFrameLog(JNIEnv* env, jclass, jstring path) {
  if (!path) return;
  const char* utf = env->GetStringUTFChars(path, nullptr);
  if (!utf) return;
  std::string target(utf);
  env->ReleaseStringUTFChars(path, utf);
#ifdef REXGLUE_ENABLE_PERF_COUNTERS
  rex::perf::SetCsvLogPath(target);
  REXLOG_INFO("[mcla] registro de fotogramas en {}", target);
#else
  REXLOG_WARN("[mcla] los contadores de rendimiento no estan compilados en esta build");
#endif
}
