// MCLA 360: the on-screen gamepad over the game.
//
// An Xbox 360 pad drawn with the Canvas:
//   left:  the left stick, the D-pad beside it, LT and LB above them, L3;
//   right: A B X Y, RT and RB above them, R3; the rest of the right half is
//          the right stick (the camera) under the finger;
//   top:   BACK and START.
//
// The state goes to the SDK's touch pad (rex_sdl_set_touch_gamepad_state, see
// android_touchpad.cpp), which publishes it as the synthetic touch
// controller, so the game sees an ordinary Xbox 360 pad and its menus and
// button prompts work unchanged.
//
// The pad hides itself while a real controller is connected. assets/touchpad.txt
// can label the buttons with what they do in the game (A=Accelerate).
//
// Adapted from the ReXGlue Android port (org.rexglue.app.TouchPadView).
// SPDX-License-Identifier: GPL-3.0-only
package com.mcla.android;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.hardware.input.InputManager;
import android.view.HapticFeedbackConstants;
import android.view.InputDevice;
import android.view.MotionEvent;
import android.view.View;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

public class TouchPadView extends View implements InputManager.InputDeviceListener {

    // --touch_controls=on: the pad stays on screen even with a real controller connected.
    static boolean sAlwaysShown = false;

    // The state goes to the SDK: the buttons are the XInput bits, the sticks
    // are -1..1 (down and right positive) and the triggers 0..1.
    static native void nativeSetState(int buttons, float lx, float ly, float rx, float ry, float lt, float rt);
    static native boolean nativeSetActive(boolean active);

    // The XInput button bits (X_INPUT_GAMEPAD_*), as the SDK expects them.
    private static final int DPAD_UP = 0x0001, DPAD_DOWN = 0x0002, DPAD_LEFT = 0x0004, DPAD_RIGHT = 0x0008;
    private static final int START = 0x0010, BACK = 0x0020, L3 = 0x0040, R3 = 0x0080, LB = 0x0100, RB = 0x0200;
    private static final int A = 0x1000, B = 0x2000, X = 0x4000, Y = 0x8000;
    private static final int LT = 100, RT = 101;  // triggers, sent as axes

    private static final int SHAPE_ROUND = 0, SHAPE_KEY = 1, SHAPE_SMALL = 2;
    private static final int ACCENT = 0xFF7AC943;

    private static final class Btn {
        final int id, shape;
        final String glyph;
        String label = "";
        final RectF rect = new RectF();
        Btn(int id, int shape, String glyph) { this.id = id; this.shape = shape; this.glyph = glyph; }
    }

    private final Btn[] mButtons = {
        new Btn(A, SHAPE_ROUND, "A"), new Btn(B, SHAPE_ROUND, "B"), new Btn(X, SHAPE_ROUND, "X"), new Btn(Y, SHAPE_ROUND, "Y"),
        new Btn(RT, SHAPE_KEY, "RT"), new Btn(RB, SHAPE_KEY, "RB"), new Btn(LT, SHAPE_KEY, "LT"), new Btn(LB, SHAPE_KEY, "LB"),
        new Btn(BACK, SHAPE_KEY, "BACK"), new Btn(START, SHAPE_KEY, "START"),
        new Btn(DPAD_UP, SHAPE_SMALL, "▲"), new Btn(DPAD_DOWN, SHAPE_SMALL, "▼"), new Btn(DPAD_LEFT, SHAPE_SMALL, "◀"), new Btn(DPAD_RIGHT, SHAPE_SMALL, "▶"),
        new Btn(L3, SHAPE_SMALL, "L3"), new Btn(R3, SHAPE_SMALL, "R3"),
    };

    // What each finger holds: a button (index into mButtons), the left stick, the right stick, or nothing.
    private static final int HOLD_NONE = -1, HOLD_STICK = -2, HOLD_CAMERA = -3;
    private final int[] mHold = new int[16];
    private final float[] mOriginX = new float[16], mOriginY = new float[16];
    private final float[] mPosX = new float[16], mPosY = new float[16];

    private float mU = 1;                     // a tenth of the screen's short side
    private float mStickX, mStickY, mStickR;  // the left stick's centre and reach
    private float mCameraR = 1;
    private float mMoveX, mMoveY;             // the left stick's current position (for drawing)
    private final Paint mFill = new Paint(Paint.ANTI_ALIAS_FLAG), mLine = new Paint(Paint.ANTI_ALIAS_FLAG),
            mText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final InputManager mInput;
    private boolean mPadActive = true;
    private boolean mAttached = false;
    // Until the game has started its input, the pad cannot attach; it keeps trying once a second.
    private final Runnable mAttachRetry = new Runnable() {
        @Override public void run() {
            if (mPadActive && !mAttached) {
                try { mAttached = nativeSetActive(true); } catch (UnsatisfiedLinkError ignored) { }
                if (!mAttached) postDelayed(this, 1000);
            }
        }
    };
    private int mLastButtons = -1;
    private float mLastLx, mLastLy, mLastRx, mLastRy, mLastLt, mLastRt;

    public TouchPadView(Context context) {
        super(context);
        for (int i = 0; i < mHold.length; ++i) mHold[i] = HOLD_NONE;
        mLine.setStyle(Paint.Style.STROKE);
        mText.setTextAlign(Paint.Align.CENTER);
        mText.setTypeface(Typeface.DEFAULT_BOLD);
        readLabels(context);
        mInput = (InputManager) context.getSystemService(Context.INPUT_SERVICE);
        if (mInput != null) mInput.registerInputDeviceListener(this, null);
        // Without this the view never gets the touches: Android only delivers
        // them to a view that says it can handle them.
        setClickable(true);
        setFocusable(true);
        updateForControllers();
    }

    // assets/touchpad.txt: BUTTON=Label per line
    private void readLabels(Context context) {
        Map<String, String> labels = new HashMap<>();
        try (BufferedReader r = new BufferedReader(new InputStreamReader(context.getAssets().open("touchpad.txt"),
                StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) {
                line = line.trim();
                int eq = line.indexOf('=');
                if (line.startsWith("#") || eq <= 0) continue;
                labels.put(line.substring(0, eq).trim().toUpperCase(), line.substring(eq + 1).trim());
            }
        } catch (Exception ignored) {
        }
        for (Btn b : mButtons) {
            String l = labels.get(b.glyph);
            if (l != null) b.label = l;
        }
    }

    // ---- real controllers

    private boolean realControllerConnected() {
        for (int id : InputDevice.getDeviceIds()) {
            InputDevice dev = InputDevice.getDevice(id);
            if (dev == null || dev.isVirtual()) continue;
            int src = dev.getSources();
            if ((src & InputDevice.SOURCE_GAMEPAD) == InputDevice.SOURCE_GAMEPAD
                    || (src & InputDevice.SOURCE_JOYSTICK) == InputDevice.SOURCE_JOYSTICK) {
                return true;
            }
        }
        return false;
    }

    private void updateForControllers() {
        boolean active = sAlwaysShown || !realControllerConnected();
        mPadActive = active;
        setVisibility(active ? VISIBLE : GONE);
        mAttached = false;
        try {
            mAttached = nativeSetActive(active) && active;
        } catch (UnsatisfiedLinkError ignored) {
        }
        // The native side just released everything, so the cached state is
        // stale: force the next touch to send it again.
        mLastButtons = -1;
        removeCallbacks(mAttachRetry);
        if (active && !mAttached) postDelayed(mAttachRetry, 1000);
    }

    @Override public void onInputDeviceAdded(int deviceId) { updateForControllers(); }
    @Override public void onInputDeviceRemoved(int deviceId) { updateForControllers(); }
    @Override public void onInputDeviceChanged(int deviceId) { updateForControllers(); }

    @Override
    protected void onDetachedFromWindow() {
        if (mInput != null) mInput.unregisterInputDeviceListener(this);
        removeCallbacks(mAttachRetry);
        super.onDetachedFromWindow();
    }

    // ---- layout

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        float u = Math.min(w, h) / 10.0f;
        mU = u;
        mCameraR = 1.6f * u;
        // the left stick, lower left
        mStickR = 1.6f * u;
        mStickX = 2.5f * u;
        mStickY = h - 2.5f * u;
        // the D-pad beside it
        float dx = 6.0f * u, dy = h - 2.0f * u, ds = 0.85f * u, dr = 0.42f * u;
        place(DPAD_UP, dx, dy - ds, dr);
        place(DPAD_DOWN, dx, dy + ds, dr);
        place(DPAD_LEFT, dx - ds, dy, dr);
        place(DPAD_RIGHT, dx + ds, dy, dr);
        // the face buttons, lower right
        float fx = w - 2.7f * u, fy = h - 2.75f * u, d = 1.22f * u, r = 0.6f * u;
        place(A, fx, fy + d, r);
        place(B, fx + d, fy, r);
        place(X, fx - d, fy, r);
        place(Y, fx, fy - d, r);
        // the shoulders, at mid height on each side
        float sw = 2.0f * u, sh = 0.78f * u;
        rect(RB, w - 0.45f * u - sw, h - 6.15f * u, sw, sh);
        rect(RT, w - 0.45f * u - sw, h - 7.15f * u, sw, sh);
        rect(LB, 0.45f * u, h - 6.15f * u, sw, sh);
        rect(LT, 0.45f * u, h - 7.15f * u, sw, sh);
        // the stick clicks beside the shoulders
        place(L3, 3.2f * u, h - 5.4f * u, 0.46f * u);
        place(R3, w - 3.2f * u, h - 5.4f * u, 0.46f * u);
        // BACK and START at the top, in the middle
        float bw = 2.2f * u, bh = 0.7f * u;
        rect(BACK, w / 2.0f - 0.25f * u - bw, 0.3f * u, bw, bh);
        rect(START, w / 2.0f + 0.25f * u, 0.3f * u, bw, bh);
        mLine.setStrokeWidth(Math.max(2.0f, 0.035f * u));
    }

    private Btn find(int id) {
        for (Btn b : mButtons) if (b.id == id) return b;
        return null;
    }

    private void place(int id, float cx, float cy, float r) {
        find(id).rect.set(cx - r, cy - r, cx + r, cy + r);
    }

    private void rect(int id, float x, float y, float w, float h) {
        find(id).rect.set(x, y, x + w, y + h);
    }

    // ---- touches

    private int buttonAt(float x, float y) {
        for (int i = 0; i < mButtons.length; ++i) {
            RectF r = mButtons[i].rect;
            float pad = Math.min(r.width(), r.height()) * 0.18f;  // a little slack around each button
            if (x >= r.left - pad && x <= r.right + pad && y >= r.top - pad && y <= r.bottom + pad) return i;
        }
        return HOLD_NONE;
    }

    private boolean inStick(float x, float y) {
        float dx = x - mStickX, dy = y - mStickY;
        return dx * dx + dy * dy <= (mStickR * 1.35f) * (mStickR * 1.35f);
    }

    private boolean held(int hold) {
        for (int h : mHold) if (h == hold) return true;
        return false;
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        int action = e.getActionMasked();
        int index = e.getActionIndex();
        switch (action) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_POINTER_DOWN: {
                int id = e.getPointerId(index);
                if (id >= mHold.length) break;
                float x = e.getX(index), y = e.getY(index);
                int b = buttonAt(x, y);
                if (b != HOLD_NONE) {
                    mHold[id] = b;
                    performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                } else if (inStick(x, y) && !held(HOLD_STICK)) {
                    mHold[id] = HOLD_STICK;
                } else if (x >= getWidth() / 2.0f && !held(HOLD_CAMERA)) {
                    mHold[id] = HOLD_CAMERA;
                } else {
                    mHold[id] = HOLD_NONE;
                }
                mOriginX[id] = mPosX[id] = x;
                mOriginY[id] = mPosY[id] = y;
                break;
            }
            case MotionEvent.ACTION_MOVE:
                for (int i = 0; i < e.getPointerCount(); ++i) {
                    int id = e.getPointerId(i);
                    if (id >= mHold.length) continue;
                    mPosX[id] = e.getX(i);
                    mPosY[id] = e.getY(i);
                    if (mHold[id] >= 0) {  // a finger sliding between buttons of a kind presses the one under it
                        int b = buttonAt(mPosX[id], mPosY[id]);
                        if (b != HOLD_NONE && b != mHold[id] && mButtons[b].shape == mButtons[mHold[id]].shape) {
                            mHold[id] = b;
                            performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                        }
                    }
                }
                break;
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_POINTER_UP:
            case MotionEvent.ACTION_CANCEL: {
                if (action == MotionEvent.ACTION_CANCEL) {
                    for (int i = 0; i < mHold.length; ++i) mHold[i] = HOLD_NONE;
                } else {
                    int id = e.getPointerId(index);
                    if (id < mHold.length) mHold[id] = HOLD_NONE;
                }
                break;
            }
        }
        sendState();
        invalidate();
        return true;
    }

    private void sendState() {
        int buttons = 0;
        float lx = 0, ly = 0, rx = 0, ry = 0, lt = 0, rt = 0;
        mMoveX = mMoveY = 0;
        for (int id = 0; id < mHold.length; ++id) {
            int h = mHold[id];
            if (h >= 0) {
                int b = mButtons[h].id;
                if (b == LT) lt = 1;
                else if (b == RT) rt = 1;
                else buttons |= b;
            } else if (h == HOLD_STICK) {
                // the left stick: how far the thumb is from its centre, full at its rim, past a small dead zone
                float dx = (mPosX[id] - mStickX) / mStickR, dy = (mPosY[id] - mStickY) / mStickR;
                float len = (float) Math.sqrt(dx * dx + dy * dy);
                if (len > 0.12f) {
                    if (len > 1) { dx /= len; dy /= len; }
                    lx = dx;
                    ly = dy;
                }
                mMoveX = lx;
                mMoveY = ly;
            } else if (h == HOLD_CAMERA) {
                float dx = (mPosX[id] - mOriginX[id]) / mCameraR;
                float dy = (mPosY[id] - mOriginY[id]) / mCameraR;
                float len = (float) Math.sqrt(dx * dx + dy * dy);
                if (len > 1) { dx /= len; dy /= len; }
                rx = dx;
                ry = dy;
            }
        }
        if (buttons == mLastButtons && lx == mLastLx && ly == mLastLy && rx == mLastRx && ry == mLastRy
                && lt == mLastLt && rt == mLastRt) {
            return;
        }
        mLastButtons = buttons; mLastLx = lx; mLastLy = ly; mLastRx = rx; mLastRy = ry; mLastLt = lt; mLastRt = rt;
        try {
            nativeSetState(buttons, lx, ly, rx, ry, lt, rt);
        } catch (UnsatisfiedLinkError ignored) {
        }
    }

    // ---- drawing

    private static int faceColor(int id) {
        switch (id) {
            case A: return 0xFF5DCB4F;  // the Xbox colours
            case B: return 0xFFE8463C;
            case X: return 0xFF3D8BF0;
            case Y: return 0xFFF5C33B;
            default: return ACCENT;
        }
    }

    @Override
    protected void onDraw(Canvas c) {
        if (!mPadActive) return;
        drawStick(c);
        for (int i = 0; i < mButtons.length; ++i) {
            Btn b = mButtons[i];
            boolean down = held(i);
            if (b.shape == SHAPE_ROUND) drawFace(c, b, down);
            else drawKey(c, b, down);
        }
        // the right stick: where a finger turns it, its ring and knob
        for (int id = 0; id < mHold.length; ++id) {
            if (mHold[id] != HOLD_CAMERA) continue;
            mFill.setColor(0x30000000);
            mLine.setColor(0x997AC943);
            c.drawCircle(mOriginX[id], mOriginY[id], mCameraR, mFill);
            c.drawCircle(mOriginX[id], mOriginY[id], mCameraR, mLine);
            float dx = mPosX[id] - mOriginX[id], dy = mPosY[id] - mOriginY[id];
            float len = (float) Math.sqrt(dx * dx + dy * dy);
            if (len > mCameraR) { dx = dx / len * mCameraR; dy = dy / len * mCameraR; }
            mFill.setColor(0x70FFFFFF);
            c.drawCircle(mOriginX[id] + dx, mOriginY[id] + dy, mCameraR * 0.4f, mFill);
        }
    }

    private void caption(Canvas c, String s, float x, float y) {
        if (s.isEmpty()) return;
        mText.setTextSize(0.22f * mU);
        mText.setColor(0xD0E8E8F0);
        mText.setShadowLayer(4, 0, 1, 0xE0000000);
        c.drawText(s, x, y, mText);
        mText.clearShadowLayer();
    }

    private void drawKey(Canvas c, Btn b, boolean down) {
        RectF r = b.rect;
        float radius = b.shape == SHAPE_SMALL ? r.width() / 2 : 0.16f * mU;
        mFill.setColor(down ? 0xE0303A28 : 0x90101216);
        c.drawRoundRect(r, radius, radius, mFill);
        mLine.setColor(down ? ACCENT : 0x90A8B4C8);
        c.drawRoundRect(r, radius, radius, mLine);
        mText.setTextSize(b.glyph.length() > 2 ? 0.26f * mU : 0.3f * mU);
        mText.setColor(down ? 0xFFFFFFFF : 0xFFC8D0DC);
        c.drawText(b.glyph, r.centerX(), r.centerY() - (mText.descent() + mText.ascent()) / 2, mText);
        caption(c, b.label, r.centerX(), r.bottom + 0.3f * mU);
    }

    private void drawFace(Canvas c, Btn b, boolean down) {
        RectF r = b.rect;
        float cx = r.centerX(), cy = r.centerY(), rad = r.width() / 2;
        int col = faceColor(b.id);
        mFill.setColor(down ? 0xF0303038 : 0xA0101216);
        c.drawCircle(cx, cy, rad, mFill);
        mLine.setColor(col);
        c.drawCircle(cx, cy, rad, mLine);
        mText.setTextSize(rad * 0.95f);
        mText.setColor(down ? 0xFFFFFFFF : col);
        c.drawText(b.glyph, cx, cy - (mText.descent() + mText.ascent()) / 2, mText);
        caption(c, b.label, cx, r.bottom + 0.3f * mU);
    }

    // the left stick: its ring, and the knob where the thumb holds it
    private void drawStick(Canvas c) {
        mFill.setColor(0x40000000);
        c.drawCircle(mStickX, mStickY, mStickR, mFill);
        mLine.setColor(0x80A8B4C8);
        c.drawCircle(mStickX, mStickY, mStickR, mLine);
        boolean down = mMoveX != 0 || mMoveY != 0 || held(HOLD_STICK);
        mFill.setColor(down ? 0xC07AC943 : 0x70C8D0DC);
        c.drawCircle(mStickX + mMoveX * mStickR * 0.6f, mStickY + mMoveY * mStickR * 0.6f, mStickR * 0.42f, mFill);
    }
}
