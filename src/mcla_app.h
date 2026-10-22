// mcla - ReXGlue Recompiled Project
//
// Customize your app by overriding virtual hooks from rex::ReXApp.

#pragma once

#include <rex/rex_app.h>

#include "mcla_scripted_pad.h"

class MclaApp : public rex::ReXApp {
 public:
  using rex::ReXApp::ReXApp;

  static std::unique_ptr<rex::ui::WindowedApp> Create(
      rex::ui::WindowedAppContext& ctx) {
    return std::unique_ptr<MclaApp>(new MclaApp(ctx, "mcla",
        PPCImageConfig));
  }

  // The Xenos GPU emulation lives in a plugin. Without this the kernel
  // stubs report "no GPU emulation loaded (gpu_plugin not set)" and the
  // game never reaches the menu.
  void OnPreSetup(rex::RuntimeConfig& config) override {
    config.gpu_plugin = "xenos";
  }

  // The runtime (and its input system) already exists here, and the guest
  // has not started polling yet. This is where the scripted gamepad goes
  // in, when MCLA_PAD_PRESS asks for it: it lets the PC send the guest a
  // button press, which is the one thing the PC cannot do otherwise.
  void OnPostSetup() override {
    mcla::InstallScriptedGamepad(runtime()->input_system());
  }

  // Override virtual hooks for customization:
  // void OnPostInitLogging() override {}
  // void OnLoadXexImage(std::string& xex_image) override {}
  // void OnPostLoadXexImage() override {}
  // void OnPostSetup() override {}
  // void OnCreateDialogs(rex::ui::ImGuiDrawer* drawer) override {}
  // std::unique_ptr<rex::ui::ImGuiDialog> CreateAchievementsOverlay() override;
  // std::unique_ptr<rex::ui::AchievementNotificationDialog>
  // CreateAchievementNotificationDialog() override;
  // void OnShutdown() override {}
  // void OnConfigurePaths(rex::PathConfig& paths) override {}
};
