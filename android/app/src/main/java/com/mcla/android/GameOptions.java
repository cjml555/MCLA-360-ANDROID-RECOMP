// MCLA 360: the launcher's options.
//
// Each option maps to a ReXGlue cvar (or to a launcher-only setting) and is
// passed to the native side on the command line, so it wins over the values
// in mcla.toml.
//
// SPDX-License-Identifier: GPL-3.0-only
package com.mcla.android;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.ArrayList;
import java.util.List;

/** The launcher's options: SDK settings, graphics and diagnostics. */
final class GameOptions {
    static final class Option {
        final String key, title, cvar, defaultValue;
        final String[] values, labels;

        Option(String key, String title, String cvar, String defaultValue,
               String[] values, String[] labels) {
            this.key = key;
            this.title = title;
            this.cvar = cvar;
            this.defaultValue = defaultValue;
            this.values = values;
            this.labels = labels;
        }

        String label(String value) {
            for (int i = 0; i < values.length; i++) if (values[i].equals(value)) return labels[i];
            return value;
        }
    }

    /** Xbox 360 language IDs. */
    static final Option LANGUAGE = new Option("language", "Idioma del juego", "user_language", "1",
            new String[]{"1", "5", "4", "3", "6"},
            new String[]{"Inglés", "Español", "Français", "Deutsch", "Italiano"});

    /** The internal resolution the game draws at. The console used 1280x720. */
    static final Option RESOLUTION = new Option("resolution", "Resolución interna", "resolution", "1280x720",
            new String[]{"640x360", "1024x576", "1280x720"},
            new String[]{"640×360 · rendimiento", "1024×576 · equilibrado", "1280×720 · calidad"});

    /** Frame pacing: the presenter waits for the display's vsync unless it is off. */
    static final Option VSYNC = new Option("vsync", "Sincronizar con la pantalla", "vsync", "true",
            new String[]{"true", "false"},
            new String[]{"Sí · ritmo del panel", "No · sin espera, más FPS y más calor"});

    /** The GPU plugin: the Xenos emulation is the only one. */
    static final Option GPU_PLUGIN = new Option("gpu_plugin", "Emulación de GPU", "gpu_plugin", "xenos",
            new String[]{"xenos"}, new String[]{"Xenos · emulación de la GPU de la 360"});

    /** The shaders are compiled on the phone the first time. */
    static final Option ASYNC_SHADERS = new Option("async_shaders", "Compilar shaders al vuelo", null, "true",
            new String[]{"true", "false"},
            new String[]{"Sí · primera carga más corta", "No · compila todo antes de jugar"});

    /** Mute, for when the phone is in a quiet place. */
    static final Option MUTE = new Option("mute", "Silenciar", "audio_mute", "false",
            new String[]{"false", "true"}, new String[]{"No", "Sí"});

    /** Diagnostics that only affect the launcher, not the game. */
    static final Option FPS_OVERLAY = new Option("fps_overlay", "Mostrar los FPS", null, "true",
            new String[]{"true", "false"}, new String[]{"Sí", "No"});

    static final Option FRAME_LOG = new Option("frame_log", "Registrar los fotogramas en CSV", null, "false",
            new String[]{"false", "true"}, new String[]{"No", "Sí · mcla-frames.csv"});

    static final Option DEBUG_OVERLAY = new Option("debug_overlay", "Overlay de depuración del SDK", null, "false",
            new String[]{"false", "true"}, new String[]{"No", "Sí"});

    static final Option[] ALL = {
            LANGUAGE,
            RESOLUTION,
            VSYNC,
            GPU_PLUGIN,
            ASYNC_SHADERS,
            MUTE,
            FPS_OVERLAY,
            FRAME_LOG,
            DEBUG_OVERLAY,
    };

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("mcla_options", Context.MODE_PRIVATE);
    }

    static String get(Context context, String key) {
        for (Option option : ALL) if (option.key.equals(key)) {
            return prefs(context).getString(key, option.defaultValue);
        }
        return null;
    }

    static void set(Context context, String key, String value) {
        prefs(context).edit().putString(key, value).apply();
    }

    /** The command-line arguments for the options that map to a cvar. */
    static List<String> arguments(Context context) {
        List<String> args = new ArrayList<>();
        for (Option option : ALL) {
            if (option.cvar == null) continue;
            String value = get(context, option.key);
            if (value != null) args.add("--" + option.cvar + "=" + value);
        }
        // The launcher-only options reach the native side as their own cvars.
        if ("true".equals(get(context, ASYNC_SHADERS.key))) {
            args.add("--async_shader_compilation=true");
        } else {
            args.add("--async_shader_compilation=false");
        }
        if ("true".equals(get(context, DEBUG_OVERLAY.key))) {
            args.add("--debug_overlay=true");
        }
        // The per-frame CSV is set by the native side (nativeStartFrameLog), not
        // here: the cvar wants a file path, and the launcher knows where the
        // logs live.
        return args;
    }
}
