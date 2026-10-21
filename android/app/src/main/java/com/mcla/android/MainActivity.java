// MCLA 360: launcher. Copy the game folder to internal storage, then press Play.
//
// Adapted from the NFS Carbon Android port (com.nfscarbon.android).
// SPDX-License-Identifier: GPL-3.0-only
package com.mcla.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;

public final class MainActivity extends Activity {
    /** Where the game folder lives: <sdcard>/MCLA. */
    public static final String GAME_FOLDER_NAME = "MCLA";

    private TextView updatesLabel;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFF0B0E13);
        root.setPadding(dp(20), dp(28), dp(20), dp(20));
        root.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView title = new TextView(this);
        title.setText("MCLA 360");
        title.setTextColor(Color.WHITE);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 30);
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, 0, 0, dp(4));
        root.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("Midnight Club: Los Angeles — recompilado con ReXGlue");
        subtitle.setTextColor(0xFF9AA4B2);
        subtitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        subtitle.setGravity(Gravity.CENTER);
        subtitle.setPadding(0, 0, 0, dp(20));
        root.addView(subtitle);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(body);
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        // --- Game folder ---
        File gameRoot = gameRoot();
        boolean present = new File(gameRoot, "default.xex").isFile();

        body.addView(section("CARPETA DEL JUEGO"));
        body.addView(info(gameRoot.getAbsolutePath()));
        body.addView(info(present
                ? "default.xex encontrado. Listo para jugar."
                : "Falta default.xex. Copia la carpeta del juego aquí."));

        if (present) {
            body.addView(action("Jugar", true, () -> {
                if (!hasStoragePermission()) {
                    askStoragePermission();
                    return;
                }
                startActivity(new Intent(this, GameActivity.class));
            }));
        } else {
            body.addView(action("Elegir carpeta", false, () ->
                    startActivityForResult(
                            new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), 1)));
        }

        // --- Options ---
        body.addView(section("OPCIONES"));
        body.addView(action("Abrir las opciones", false, this::showOptions));

        // --- Updates ---
        body.addView(section("ACTUALIZACIONES"));
        body.addView(action("Buscar actualizaciones", false, this::checkUpdates));
        updatesLabel = info("");
        body.addView(updatesLabel);

        // --- Storage permission ---
        if (!hasStoragePermission()) {
            body.addView(section("PERMISO DE ALMACENAMIENTO"));
            body.addView(info("Android 11+ necesita acceso a todos los archivos "
                    + "para leer la carpeta del juego."));
            body.addView(action("Dar permiso", false, this::askStoragePermission));
        }

        // --- Notes ---
        body.addView(section("NOTAS"));
        body.addView(info("El port aún no incluye los datos del juego: copia tú "
                + "el contenido de tu ISO (default.xex, *.bik, *.rpf) en la "
                + "carpeta indicada."));
        body.addView(info("La primera carga compila los shaders y tarda unos "
                + "segundos. El registro queda en Android/data/com.mcla.android/files/logs."));

        setContentView(root);
    }

    private File gameRoot() {
        return new File(Environment.getExternalStorageDirectory(), GAME_FOLDER_NAME);
    }

    private boolean hasStoragePermission() {
        if (Build.VERSION.SDK_INT < 30) return true;
        return Environment.isExternalStorageManager();
    }

    private void askStoragePermission() {
        if (Build.VERSION.SDK_INT >= 30) {
            startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                    Uri.parse("package:" + getPackageName())));
        }
    }

    // --- Small view helpers ---

    private TextView section(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextColor(0xFF6FC3FF);
        v.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        v.setPadding(0, dp(18), 0, dp(6));
        return v;
    }

    private TextView info(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextColor(0xFFC7D0DB);
        v.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        v.setPadding(0, 0, 0, dp(8));
        return v;
    }

    private Button action(String text, boolean primary, Runnable onClick) {
        Button b = new Button(this);
        b.setText(text);
        b.setOnClickListener(v -> onClick.run());
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        b.setTextColor(Color.WHITE);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(10));
        bg.setColor(primary ? 0xFF2C6BED : 0xFF232A34);
        b.setBackground(bg);
        b.setPadding(dp(16), dp(14), dp(16), dp(14));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = dp(10);
        b.setLayoutParams(lp);
        return b;
    }

    private int dp(int value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value,
                getResources().getDisplayMetrics()));
    }

    // --- Options ---

    /** A dialog with one switch-like row per option. */
    private void showOptions() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(10), dp(20), dp(10));

        for (GameOptions.Option option : GameOptions.ALL) {
            String current = GameOptions.get(this, option.key);
            TextView row = new TextView(this);
            row.setText(option.title + "\n" + option.label(current));
            row.setTextColor(0xFFC7D0DB);
            row.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
            row.setPadding(0, dp(10), 0, dp(10));
            row.setOnClickListener(v -> {
                int index = 0;
                for (int i = 0; i < option.values.length; i++) {
                    if (option.values[i].equals(current)) index = i;
                }
                index = (index + 1) % option.values.length;
                GameOptions.set(this, option.key, option.values[index]);
                showOptions();  // reopen, so the new value is visible
            });
            box.addView(row);
        }

        new AlertDialog.Builder(this)
                .setTitle("Opciones")
                .setView(box)
                .setPositiveButton("Cerrar", null)
                .show();
    }

    // --- Updates ---

    /** Looks for a newer release on GitHub. Nothing is downloaded or installed. */
    private void checkUpdates() {
        if (updatesLabel == null) return;
        updatesLabel.setText("Buscando…");
        ReleaseUpdates.check(this, true, result -> {
            if (result.error != null) {
                updatesLabel.setText(result.error);
            } else if (result.tag == null || result.tag.isEmpty()) {
                updatesLabel.setText("No se encontró ninguna versión publicada.");
            } else if (ReleaseVersion.newer(result.tag, ReleaseUpdates.installed(this))) {
                updatesLabel.setText("Hay una versión nueva: " + result.tag
                        + ". Descárgala desde " + result.url);
            } else {
                updatesLabel.setText("Esta es la última versión (" + result.tag + ").");
            }
        });
    }
}
