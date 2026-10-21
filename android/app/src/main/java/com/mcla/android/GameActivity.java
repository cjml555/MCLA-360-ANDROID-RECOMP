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
import android.os.Bundle;
import android.os.Environment;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;

import org.libsdl.app.SDLActivity;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

public final class GameActivity extends SDLActivity {
    private static final String TAG = "MCLA";

    private String gameRoot;
    private String userRoot;
    private String cacheRoot;

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
