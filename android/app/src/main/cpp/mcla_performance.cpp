// MCLA 360: performance counters for the launcher (FPS, frame time, CSV log).
//
// The SDK keeps a registry of perf counters (rex::perf::CounterId) that its
// debug overlay reads. Nothing in the SDK sets the frame counters, so this
// file does it: it hooks the Vulkan present path (where a frame ends) and
// publishes the time between frames.
//
// SPDX-License-Identifier: BSD-3-Clause

#include <jni.h>

#include <chrono>
#include <cstdint>
#include <string>

#include <rex/cvar.h>
#include <rex/logging.h>
#include <rex/perf/counter.h>

#if defined(__ANDROID__)
#include <dlfcn.h>
#endif

namespace {

// The number of frames published so far. The launcher reads it to work out
// the average frame time, and the present path publishes the time of the last
// frame.
std::atomic<uint64_t> g_frames{0};
std::atomic<int64_t> g_last_frame_us{0};

// The hook in the Vulkan command processor. The SDK calls it after every
// swap; it returns the number of frames so far.
using FramesFn = uint64_t (*)();
FramesFn g_frames_fn = nullptr;

int64_t NowUs() {
  return std::chrono::duration_cast<std::chrono::microseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

}  // namespace

extern "C" {

// Called from the patched command processor, right after each swap.
__attribute__((visibility("default"))) void MclaNotifyFramePresented() {
  const int64_t now = NowUs();
  const int64_t last = g_last_frame_us.load(std::memory_order_relaxed);
  if (last > 0 && now > last) {
    // The counters are compiled out in Release by default, so guard them.
#ifdef REXGLUE_ENABLE_PERF_COUNTERS
    rex::perf::SetCounter(rex::perf::CounterId::kFrameTimeUs, now - last);
    rex::perf::SetCounter(rex::perf::CounterId::kFps, 1000000 / (now - last));
#endif
  }
  g_last_frame_us.store(now, std::memory_order_relaxed);
  g_frames.fetch_add(1, std::memory_order_relaxed);
}

__attribute__((visibility("default"))) uint64_t MclaFramesPresented() {
  return g_frames.load(std::memory_order_relaxed);
}

// Resolves the SDK's own counter of presented frames, if there is one. The
// SDK's perf counters are a registry the runtime fills in; the frame counter
// is the one this port needs.
__attribute__((visibility("default"))) void MclaResolveSdkCounters() {
#if defined(__ANDROID__)
  // The runtime is loaded in the same process; its symbols may be hidden.
  void* handle = dlopen("librexruntime.so", RTLD_NOW | RTLD_NOLOAD);
  if (!handle) handle = dlopen("librexruntime.so", RTLD_NOW);
  if (!handle) return;
  g_frames_fn = reinterpret_cast<FramesFn>(dlsym(handle, "MclaFramesPresented"));
  dlclose(handle);
#endif
}

}  // extern "C"

extern "C" JNIEXPORT jlong JNICALL
Java_com_mcla_android_GameActivity_nativeFrameTimeUs(JNIEnv*, jclass) {
  // The average time of a frame, in microseconds. Zero means "no frames
  // yet" (or nothing drawn for a while): the launcher shows a dash then.
#ifdef REXGLUE_ENABLE_PERF_COUNTERS
  const int64_t snapshot = rex::perf::GetSnapshotCounter(rex::perf::CounterId::kFrameTimeUs);
  if (snapshot > 0) return snapshot;
#endif
  const int64_t last = g_last_frame_us.load(std::memory_order_relaxed);
  return last > 0 ? last : 0;
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_mcla_android_GameActivity_nativeFramesPresented(JNIEnv*, jclass) {
  return static_cast<jlong>(g_frames.load(std::memory_order_relaxed));
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
