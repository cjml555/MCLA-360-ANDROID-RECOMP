// MCLA 360: the scripted gamepad's implementation.
//
// See mcla_scripted_pad.h for what it is for.
//
// SPDX-License-Identifier: GPL-3.0-only

#include "mcla_scripted_pad.h"

#include <cstdlib>
#include <cstring>
#include <string>

#include <rex/input/input_system.h>
#include <rex/logging.h>

namespace mcla {

namespace {

// A device id of our own: the SDK's drivers use ids from their own space
// (the keyboard one uses 0x4D4E4B00), so this cannot collide.
constexpr rex::input::DeviceId kScriptedDevice = static_cast<rex::input::DeviceId>(0x53435250);

// How long the button stays down.
constexpr double kHoldSeconds = 0.2;

// Parses one "<seconds>:<mask>" entry. The mask is hexadecimal, with or
// without the 0x prefix. Returns false on anything malformed.
bool ParsePress(const std::string& text, Press* out) {
  const size_t colon = text.find(':');
  if (colon == std::string::npos || colon == 0 || colon + 1 >= text.size()) {
    return false;
  }
  const std::string seconds = text.substr(0, colon);
  const std::string mask = text.substr(colon + 1);

  double at = 0.0;
  try {
    size_t consumed = 0;
    at = std::stod(seconds, &consumed);
    if (consumed != seconds.size()) {
      return false;
    }
  } catch (...) {
    return false;
  }

  uint16_t buttons = 0;
  try {
    size_t consumed = 0;
    const unsigned long value = std::stoul(mask, &consumed, 0);
    if (consumed != mask.size() || value > 0xFFFF) {
      return false;
    }
    buttons = static_cast<uint16_t>(value);
  } catch (...) {
    return false;
  }

  out->at_seconds = at;
  out->buttons = buttons;
  return true;
}

}  // namespace

std::vector<Press> ReadPressScript() {
  std::vector<Press> presses;
  const char* raw = std::getenv("MCLA_PAD_PRESS");
  if (!raw || !*raw) {
    return presses;
  }
  const std::string text(raw);
  size_t start = 0;
  while (start <= text.size()) {
    const size_t comma = text.find(',', start);
    const std::string piece =
        text.substr(start, comma == std::string::npos ? std::string::npos : comma - start);
    if (!piece.empty()) {
      Press press;
      if (ParsePress(piece, &press)) {
        presses.push_back(press);
      } else {
        REXLOG_WARN("mcla: ignored malformed press entry \"{}\"", piece);
      }
    }
    if (comma == std::string::npos) {
      break;
    }
    start = comma + 1;
  }
  return presses;
}

ScriptedGamepadDriver::ScriptedGamepadDriver(std::vector<Press> presses)
    : InputDriver(nullptr, 0), presses_(std::move(presses)) {}

ScriptedGamepadDriver::~ScriptedGamepadDriver() = default;

X_STATUS ScriptedGamepadDriver::Setup() { return X_STATUS_SUCCESS; }

void ScriptedGamepadDriver::EnumerateDevices(std::vector<rex::input::DeviceInfo>& out) {
  rex::input::DeviceInfo info;
  info.id = kScriptedDevice;
  info.name = "MCLA Scripted Gamepad";
  info.guid = "mcla-scripted-gamepad";
  // Synthetic: the SDK routes it to guest user 0, the same slot the touch
  // overlay takes on Android.
  info.synthetic = true;
  out.push_back(info);
}

X_RESULT ScriptedGamepadDriver::GetDeviceState(rex::input::DeviceId id,
                                                rex::input::X_INPUT_STATE* out_state) {
  if (id != kScriptedDevice) {
    return X_ERROR_DEVICE_NOT_CONNECTED;
  }

  // The clock starts at the first poll. The guest does not ask for the pad
  // until it reaches the title screen, half a minute into the run, so the
  // presses are scheduled from there: "at 2 seconds" means two seconds
  // after the game first looks at the pad.
  if (!started_) {
    started_ = true;
    start_ = std::chrono::steady_clock::now();
    REXLOG_INFO("mcla: scripted gamepad clock starts");
  }

  const double elapsed =
      std::chrono::duration<double>(std::chrono::steady_clock::now() - start_).count();

  uint16_t buttons = 0;
  for (const Press& press : presses_) {
    if (elapsed >= press.at_seconds && elapsed < press.at_seconds + kHoldSeconds) {
      buttons |= press.buttons;
    }
  }

  if (buttons != last_buttons_) {
    last_buttons_ = buttons;
    packet_number_++;
    if (buttons != 0) {
      REXLOG_INFO("mcla: scripted gamepad pressing 0x{:04X} at t={:.2f}s", buttons, elapsed);
    }
  }

  if (out_state) {
    out_state->packet_number = packet_number_;
    out_state->gamepad.buttons = buttons;
    out_state->gamepad.left_trigger = 0;
    out_state->gamepad.right_trigger = 0;
    out_state->gamepad.thumb_lx = 0;
    out_state->gamepad.thumb_ly = 0;
    out_state->gamepad.thumb_rx = 0;
    out_state->gamepad.thumb_ry = 0;
  }
  return X_ERROR_SUCCESS;
}

X_RESULT ScriptedGamepadDriver::GetDeviceCapabilities(rex::input::DeviceId id, uint32_t flags,
                                                      rex::input::X_INPUT_CAPABILITIES* out_caps) {
  if (id != kScriptedDevice) {
    return X_ERROR_DEVICE_NOT_CONNECTED;
  }
  if (out_caps) {
    std::memset(out_caps, 0, sizeof(*out_caps));
    out_caps->type = 0x01;
    out_caps->sub_type = 0x01;
  }
  return X_ERROR_SUCCESS;
}

X_RESULT ScriptedGamepadDriver::SetDeviceVibration(rex::input::DeviceId id,
                                                    rex::input::X_INPUT_VIBRATION* vibration) {
  if (id != kScriptedDevice) {
    return X_ERROR_DEVICE_NOT_CONNECTED;
  }
  return X_ERROR_SUCCESS;
}

X_RESULT ScriptedGamepadDriver::GetDeviceKeystroke(rex::input::DeviceId id, uint32_t flags,
                                                    rex::input::X_INPUT_KEYSTROKE* out_keystroke) {
  if (id != kScriptedDevice) {
    return X_ERROR_DEVICE_NOT_CONNECTED;
  }
  // The scripted pad has no keystrokes to report: the guest asks for
  // them only for text entry, which a gamepad does not do.
  return X_ERROR_INVALID_PARAMETER;
}

void InstallScriptedGamepad(rex::system::IInputSystem* input_system) {
  if (!input_system) {
    return;
  }
  std::vector<Press> presses = ReadPressScript();
  if (presses.empty()) {
    return;
  }
  // The runtime's input system is the SDK's concrete InputSystem, the one
  // that owns the drivers.
  auto* concrete = static_cast<rex::input::InputSystem*>(input_system);
  concrete->AddDriver(std::make_unique<ScriptedGamepadDriver>(std::move(presses)));
  REXLOG_INFO("mcla: scripted gamepad installed");
}

}  // namespace mcla
