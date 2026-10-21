// mcla - ReXGlue Recompiled Project
//
// Customize your app by overriding virtual hooks from rex::ReXApp.

#pragma once

#include <rex/rex_app.h>

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

#if REX_PLATFORM_ANDROID
  // The settings (mcla.toml) live in the app's own folder, the one the
  // launcher points at with REX_APP_FOLDER. Without this the SDK looks for
  // them next to the executable, which on Android is /system/bin.
  void OnConfigurePaths(rex::PathConfig& paths) override {
    paths.config_path = paths.user_data_root / "mcla.toml";
  }
#endif

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
