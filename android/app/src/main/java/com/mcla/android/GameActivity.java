// MCLA 360: the activity that runs the recompiled game.
//
// The native side is ReXGlue's SDL application, so this extends SDLActivity:
// the C++ main() in mcla_entry.cpp registers the "mcla" app creator and the
// SDL runtime owns the surface and the message loop.
//
// Adapted from the NFS Carbon Android port (com.nfscarbon.android).
// SPDX-License-Identifier: GPL-3.0-only
package com.mcla.android;

import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Environment;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;

import org.libsdl.app.SDLActivity;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;

public final class GameActivity extends SDLActivity {
    private static final String TAG = "MCLA";

    private String gameRoot;
    private String userRoot;
    private String cacheRoot;

    /** The FPS readout, on top of the game. */
    private TextView fpsLabel;
    private final android.os.Handler frameHandler =
            new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable updateFrames = new Runnable() {
        @Override public void run() {
            if (fpsLabel == null || isFinishing()) return;
            try {
                long frameUs = nativeFrameTimeUs();
                fpsLabel.setText(frameUs > 0
                        ? String.format(java.util.Locale.ROOT, "%.0f FPS · %.1f ms",
                                1000000.0 / frameUs, frameUs / 1000.0)
                        : "FPS · cargando…");
            } catch (UnsatisfiedLinkError ignored) {
                fpsLabel.setText("FPS · cargando…");
            }
            frameHandler.postDelayed(this, 1000);
        }
    };

    private static native long nativeFrameTimeUs();
    private static native long nativeFramesPresented();
    private static native void nativeStartFrameLog(String path);

    @Override
    protected void onCreate(Bundle state) {
        File appRoot = new File(getFilesDir(), "mcla");
        gameRoot = new File(Environment.getExternalStorageDirectory(),
                MainActivity.GAME_FOLDER_NAME).getAbsolutePath();
        userRoot = new File(appRoot, "user").getAbsolutePath();
        cacheRoot = new File(appRoot, "cache").getAbsolutePath();
        new File(userRoot).mkdirs();
        new File(cacheRoot).mkdirs();

        // The native side keeps mcla.toml, the pipeline cache and its logs in
        // the "executable folder". Under app_process that would be /system/bin,
        // so point it at the app's own writable directory.
        try {
            Os.setenv("REX_APP_FOLDER", userRoot, true);
        } catch (ErrnoException e) {
            Log.w(TAG, "REX_APP_FOLDER", e);
        }

        setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE);
        super.onCreate(state);

        // The FPS readout, on top of the game, when the option is on.
        if ("true".equals(GameOptions.get(this, GameOptions.FPS_OVERLAY.key))) {
            fpsLabel = new TextView(this);
            fpsLabel.setTextColor(Color.WHITE);
            fpsLabel.setTextSize(12);
            fpsLabel.setPadding(dp(8), dp(4), dp(8), dp(4));
            fpsLabel.setBackgroundColor(0x99081017);
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                    Gravity.TOP | Gravity.CENTER_HORIZONTAL);
            lp.topMargin = dp(12);
            addContentView(fpsLabel, lp);
            frameHandler.postDelayed(updateFrames, 1000);
        }
    }

    @Override
    protected void onDestroy() {
        frameHandler.removeCallbacks(updateFrames);
        super.onDestroy();
    }

    private int dp(int value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value,
                getResources().getDisplayMetrics()));
    }

    @Override
    protected String[] getArguments() {
        List<String> args = new ArrayList<>();
        args.add("--game_data_root=" + gameRoot);
        args.add("--user_data_root=" + userRoot);
        args.add("--cache_root=" + cacheRoot);
        args.add("--metadata_root=" + userRoot);

        // The log goes to the app's external folder so it can be read over USB.
        File external = getExternalFilesDir(null);
        File logs = external != null ? new File(external, "logs") : new File(userRoot, "logs");
        if (!logs.mkdirs() && !logs.isDirectory()) logs = new File(userRoot, "logs");
        logs.mkdirs();
        args.add("--log_file=" + new File(logs, "mcla.log").getAbsolutePath());

        // The per-frame CSV, when the option is on. The native side writes it.
        if ("true".equals(GameOptions.get(this, GameOptions.FRAME_LOG.key))) {
            File csv = new File(logs, "mcla-frames.csv");
            try {
                nativeStartFrameLog(csv.getAbsolutePath());
            } catch (UnsatisfiedLinkError ignored) {
                Log.w(TAG, "nativeStartFrameLog", ignored);
            }
        }

        // Testing: one extra argument per line in
        // Android/data/com.mcla.android/files/args.txt (written over USB; the
        // app never creates it).
        if (external != null) {
            File argsFile = new File(external, "args.txt");
            if (argsFile.isFile()) {
                try {
                    for (String line : readLines(argsFile)) {
                        if (!line.trim().isEmpty()) args.add(line.trim());
                    }
                } catch (Exception e) {
                    Log.w(TAG, "args.txt", e);
                }
            }
        }
        return args.toArray(new String[0]);
    }

    private static List<String> readLines(File file) throws Exception {
        List<String> lines = new ArrayList<>();
        try (java.io.BufferedReader reader = new java.io.BufferedReader(
                new java.io.InputStreamReader(new java.io.FileInputStream(file)))) {
            String line;
            while ((line = reader.readLine()) != null) lines.add(line);
        }
        return lines;
    }
}
