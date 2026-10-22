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

// Parses one "<seconds>:<mask>" entry, or "<seconds>:s:<lx>:<ly>[:<rx>:<ry>]"
// for a stick deflection. The mask is hexadecimal, with or without the 0x
// prefix; the axes are fractions from -1 to 1. Returns false on anything
// malformed.
bool ParsePress(const std::string& text, Press* out) {
  const size_t colon = text.find(':');
  if (colon == std::string::npos || colon == 0 || colon + 1 >= text.size()) {
    return false;
  }
  const std::string seconds = text.substr(0, colon);
  const std::string rest = text.substr(colon + 1);

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

  // A stick entry: "s:<lx>:<ly>" or "s:<lx>:<ly>:<rx>:<ry>", optionally
  // followed by "@<hold_seconds>" to say how long the deflection lasts.
  if (rest.rfind("s:", 0) == 0) {
    std::string axes = rest.substr(2);
    double hold = 0.0;
    // The hold time is a suffix, separated by '@', so it cannot be
    // confused with an axis: "s:0:-1@5" is the left stick down for five
    // seconds, and "s:0:-1:0:0" is both sticks centred.
    const size_t at_sign = axes.find('@');
    if (at_sign != std::string::npos) {
      const std::string hold_text = axes.substr(at_sign + 1);
      axes = axes.substr(0, at_sign);
      try {
        size_t consumed = 0;
        hold = std::stod(hold_text, &consumed);
        if (consumed != hold_text.size() || hold < 0.0) {
          return false;
        }
      } catch (...) {
        return false;
      }
    }
    std::vector<std::string> parts;
    size_t begin = 0;
    while (begin <= axes.size()) {
      const size_t sep = axes.find(':', begin);
      parts.push_back(axes.substr(begin, sep == std::string::npos ? std::string::npos : sep - begin));
      if (sep == std::string::npos) {
        break;
      }
      begin = sep + 1;
    }
    if (parts.size() != 2 && parts.size() != 4) {
      return false;
    }
    float values[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    for (size_t i = 0; i < parts.size(); i++) {
      try {
        size_t consumed = 0;
        const double value = std::stod(parts[i], &consumed);
        if (consumed != parts[i].size() || value < -1.0 || value > 1.0) {
          return false;
        }
        values[i] = static_cast<float>(value);
      } catch (...) {
        return false;
      }
    }
    out->at_seconds = at;
    out->lx = values[0];
    out->ly = values[1];
    out->rx = values[2];
    out->ry = values[3];
    out->hold_seconds = hold;
    return true;
  }

  uint16_t buttons = 0;
  try {
    size_t consumed = 0;
    const unsigned long value = std::stoul(rest, &consumed, 0);
    if (consumed != rest.size() || value > 0xFFFF) {
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
    : InputDriver(nullptr, 0) {
  schedule_.reserve(presses.size());
  for (const Press& press : presses) {
    Scheduled scheduled;
    scheduled.press = press;
    schedule_.push_back(scheduled);
  }
}

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

  // How many times the guest has looked at the pad. The guest only asks
  // while it is running its menus, and it stops asking while it compiles
  // shaders, so the poll count is what says whether a gesture had a
  // chance of being seen.
  {
    static uint32_t polls = 0;
    if (++polls % 50 == 0) {
      REXLOG_INFO("mcla: scripted gamepad poll #{}", polls);
    }
  }

  const double elapsed =
      std::chrono::duration<double>(std::chrono::steady_clock::now() - start_).count();

  // Each gesture advances by ONE poll, not by the clock: the guest has to
  // see the button go down and then go up again, and the only thing that
  // can guarantee that is a poll. A gesture that is due stays down until
  // the next poll releases it, so a slow polling rate delays the release
  // but never loses the gesture.
  //
  // A stick is held for kStickPolls polls instead of one: it is a
  // position, not an edge, and the guest may need to see it over several
  // frames to move a cursor. When the script asks for a hold time, that
  // wins: the stick is held until the time is up. The game polls the pad
  // about four times a second, so a poll-based hold is a second or so,
  // and steering needs longer than that.
  uint16_t buttons = 0;
  int16_t lx = 0;
  int16_t ly = 0;
  int16_t rx = 0;
  int16_t ry = 0;

  // The XInput axes are 16-bit signed, full deflection at INT16_MAX.
  const auto to_axis = [](float fraction) {
    return static_cast<int16_t>(fraction * INT16_MAX);
  };

  for (Scheduled& scheduled : schedule_) {
    switch (scheduled.state) {
      case PressState::kPending:
        if (elapsed >= scheduled.press.at_seconds) {
          scheduled.state = PressState::kDown;
          scheduled.buttons = scheduled.press.buttons;
          scheduled.polls_left = scheduled.press.IsStick() ? kStickPolls : 1;
          buttons |= scheduled.buttons;
          lx = to_axis(scheduled.press.lx);
          ly = to_axis(scheduled.press.ly);
          rx = to_axis(scheduled.press.rx);
          ry = to_axis(scheduled.press.ry);
        }
        break;
      case PressState::kDown: {
        // A hold time, when the script gives one, is what decides when
        // the stick comes back. Otherwise the poll count does: the guest
        // has to see the deflection over a few polls.
        const bool hold_expired =
            scheduled.press.hold_seconds > 0.0 &&
            elapsed >= scheduled.press.at_seconds + scheduled.press.hold_seconds;
        const bool polls_left = --scheduled.polls_left > 0;
        if (hold_expired) {
          // Time is up: release it.
          scheduled.state = PressState::kUp;
        } else if (scheduled.press.hold_seconds > 0.0) {
          // Still within the hold time: keep the deflection.
          buttons |= scheduled.buttons;
          lx = to_axis(scheduled.press.lx);
          ly = to_axis(scheduled.press.ly);
          rx = to_axis(scheduled.press.rx);
          ry = to_axis(scheduled.press.ry);
        } else if (polls_left) {
          // Still holding the stick: keep the deflection.
          buttons |= scheduled.buttons;
          lx = to_axis(scheduled.press.lx);
          ly = to_axis(scheduled.press.ly);
          rx = to_axis(scheduled.press.rx);
          ry = to_axis(scheduled.press.ry);
        } else {
          // The guest has seen it: release it.
          scheduled.state = PressState::kUp;
        }
        break;
      }
      case PressState::kUp:
        // The release was reported on the previous poll: done.
        scheduled.state = PressState::kDone;
        break;
      case PressState::kDone:
        break;
    }
  }

  if (buttons != last_buttons_ || lx != last_lx_ || ly != last_ly_ || rx != last_rx_ ||
      ry != last_ry_) {
    const bool was_active = last_buttons_ != 0 || last_lx_ != 0 || last_ly_ != 0 ||
                            last_rx_ != 0 || last_ry_ != 0;
    last_buttons_ = buttons;
    last_lx_ = lx;
    last_ly_ = ly;
    last_rx_ = rx;
    last_ry_ = ry;
    packet_number_++;
    if (buttons != 0 || lx != 0 || ly != 0 || rx != 0 || ry != 0) {
      REXLOG_INFO("mcla: scripted gamepad buttons=0x{:04X} stick=({},{},{},{}) at t={:.2f}s",
                  buttons, lx, ly, rx, ry, elapsed);
    } else if (was_active) {
      // The release. It has to be logged too: without it there is no way
      // to tell a stick that was held for its full time from one that was
      // cut short.
      REXLOG_INFO("mcla: scripted gamepad released at t={:.2f}s", elapsed);
    }
  }

  if (out_state) {
    out_state->packet_number = packet_number_;
    out_state->gamepad.buttons = buttons;
    out_state->gamepad.left_trigger = 0;
    out_state->gamepad.right_trigger = 0;
    out_state->gamepad.thumb_lx = lx;
    out_state->gamepad.thumb_ly = ly;
    out_state->gamepad.thumb_rx = rx;
    out_state->gamepad.thumb_ry = ry;
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
