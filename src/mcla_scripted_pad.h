// MCLA 360: a scripted gamepad, for testing without a phone.
//
// The port's remaining unknown is whether "PRESS >" on the title screen
// actually advances the game. On the phone that needs the device: a real
// touch, the screen in the foreground (Android kills the process
// otherwise), and someone to press it. On the PC there is no way to send
// the game a button press at all: the X server in this session refuses
// every synthetic key event, and the SDL build is static, so SDL_PushEvent
// from another process never reaches the game's queue.
//
// This driver closes that gap. It is an ordinary rex::input::InputDriver
// that reports one synthetic device and holds a button down on a timer,
// so the guest sees exactly what it would see on the phone.
//
// It is installed from the app, through the SDK's public API:
//
//   InputSystem::AddDriver(std::make_unique<ScriptedGamepadDriver>(...))
//
// The device is synthetic, so the SDK's SlotAssignment routes it to guest
// user 0, the same slot the touch overlay uses on Android. That is the
// point: the PC then exercises the same guest code path as the phone.
//
// Usage: the press script is read from the MCLA_PAD_PRESS environment
// variable, as "<seconds>:<xinput button mask>", optionally repeated with
// commas for a sequence:
//
//   MCLA_PAD_PRESS=8:0x1000 ./out/pc/mcla ...
//   MCLA_PAD_PRESS=8:0x1000,12:0x1000,16:0x0010 ./out/pc/mcla ...
//
// The mask is the XInput one, the same the Android overlay uses:
// A = 0x1000, B = 0x2000, X = 0x4000, Y = 0x8000, START = 0x0010,
// BACK = 0x0020, D-pad = 0x0001..0x0008.
//
// The times are relative to the first poll, not to the start of the run:
// the guest does not look at the pad until it reaches the title screen,
// which is half a minute in. So "2:0x1000" means "press A two seconds
// after the game first asks for the pad".
//
// The button is held for a fifth of a second: long enough for the guest to
// poll it (it polls several times per frame) and short enough to look like
// a tap.
//
// SPDX-License-Identifier: GPL-3.0-only

#pragma once

#include <chrono>
#include <cstdint>
#include <vector>

#include <rex/input/device.h>
#include <rex/input/input.h>
#include <rex/input/input_driver.h>
#include <rex/system/interfaces/input.h>

namespace mcla {

// The SDK's status codes live in the rex namespace.
using rex::X_RESULT;
using rex::X_STATUS;

// One entry of the press script: when to press, and which buttons.
struct Press {
  double at_seconds = 0.0;
  uint16_t buttons = 0;
};

// Reads the press script from the MCLA_PAD_PRESS environment variable.
// Returns an empty vector when it is unset, malformed, or empty.
std::vector<Press> ReadPressScript();

// A gamepad that presses buttons on a timer. The guest polls it through
// the SDK's normal input path, so whatever it does with a button press on
// the phone it does here too.
//
// A press is delivered by POLL, not by a stopwatch: the script says "at
// second N" and the press is held from then on, until the guest has seen
// it come up and go down again. A fixed-length window would drop presses
// whenever the guest was busy (compiling shaders slows the polling down
// to a crawl, and a 200 ms window can fall entirely between two polls).
class ScriptedGamepadDriver final : public rex::input::InputDriver {
 public:
  explicit ScriptedGamepadDriver(std::vector<Press> presses);
  ~ScriptedGamepadDriver() override;

  X_STATUS Setup() override;

  void EnumerateDevices(std::vector<rex::input::DeviceInfo>& out) override;

  X_RESULT GetDeviceState(rex::input::DeviceId id, rex::input::X_INPUT_STATE* out_state) override;
  X_RESULT GetDeviceCapabilities(rex::input::DeviceId id, uint32_t flags,
                                 rex::input::X_INPUT_CAPABILITIES* out_caps) override;
  X_RESULT SetDeviceVibration(rex::input::DeviceId id, rex::input::X_INPUT_VIBRATION* vibration) override;
  X_RESULT GetDeviceKeystroke(rex::input::DeviceId id, uint32_t flags,
                               rex::input::X_INPUT_KEYSTROKE* out_keystroke) override;

 private:
  // The state of one scheduled press.
  //
  // A press is not a window of time: it is a sequence of polls. The guest
  // sees the button go down, then up, and that pair is what it acts on. So
  // the press waits for the polls to happen instead of hoping the guest
  // happens to look at the pad during a fixed window.
  enum class PressState {
    kPending,   // not due yet
    kDown,      // due: the button goes down and stays down
    kUp,        // the guest has seen it down: release it
    kDone,      // released and delivered
  };

  struct Scheduled {
    Press press;
    PressState state = PressState::kPending;
    uint16_t buttons = 0;  // the buttons this press holds down
  };

  std::vector<Scheduled> schedule_;
  // The clock starts at the first poll, not at construction: the guest does
  // not ask for the pad until it reaches the title screen, which is half a
  // minute into the run. A clock that started at construction would fire
  // every press long before anybody was listening.
  std::chrono::steady_clock::time_point start_{};
  bool started_ = false;
  uint16_t last_buttons_ = 0;
  uint32_t packet_number_ = 0;
};

// Installs the scripted gamepad into the SDK's input system. Does nothing
// when the press script is empty, so the normal runs are unaffected.
//
// Takes the runtime's IInputSystem: the concrete InputSystem is what knows
// about drivers, and the cast happens here rather than in the caller.
//
// The device is registered as a driver of its own, not as a synthetic
// "keyboard and mouse" one: it does not fight the MNK driver for the
// guest's attention.
void InstallScriptedGamepad(rex::system::IInputSystem* input_system);

}  // namespace mcla
