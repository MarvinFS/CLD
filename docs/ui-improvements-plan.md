# CLD UI Improvements Plan

## Issues Overview

1. **About Dialog**: Black titlebar, full URL text instead of clickable link
2. **Tray Icon Invisible**: Gray #666666 disappears on dark Windows taskbar
3. **Overlay Close Bug** (CRITICAL): Right-click destroys overlay, prevents re-show, hangs Settings
4. **Tiny Overlay Redesign**: Current 28x28 gray dot is ugly, needs modern pill-shaped widget

## Implementation Order

Issue 3 (critical bug) -> Issue 2 (quick fix) -> Issue 1 (small improvement) -> Issue 4 (major redesign)

---

## Issue 3: Overlay Close Bug (CRITICAL)

**Problem**: When user right-clicks to close overlay, `_close()` destroys the tkinter root and sets `self._overlay = None`. Subsequent tray "Show Overlay" fails silently, and Settings creates orphan Tk() causing deadlock.

**Solution**: Hide instead of destroy on close.

### File: src/cld/ui/overlay.py

Change `_close()` method (lines 537-546):
```python
def _close(self):
    """Close (hide) the overlay."""
    self._running = False
    if self._animation_id and self._root:
        self._root.after_cancel(self._animation_id)
        self._animation_id = None
    # Hide instead of destroy
    if self._root:
        self._root.withdraw()
    if self.on_close:
        self.on_close()
```

### File: src/cld/daemon_service.py

Change `_on_overlay_close()` (remove the `self._overlay = None` line):
```python
def _on_overlay_close(self):
    """Called when overlay is closed (hidden) by user."""
    # Overlay is just hidden, not destroyed - keep the reference
    if self._tray:
        self._tray.set_overlay_visible(False)
```

Change `_on_tray_show_overlay()` to restart animation:
```python
def _on_tray_show_overlay(self):
    def do_show():
        if self._overlay:
            self._overlay._running = True  # Resume
            self._overlay.unhide()
            if self._tray:
                self._tray.set_overlay_visible(True)
    self._main_thread_queue.put(do_show)
```

---

## Issue 2: Tray Icon Invisible in Dark Theme

**Problem**: Line 78 uses `#666666` gray which is invisible on dark Windows taskbar.

### File: src/cld/ui/tray.py

Change color on line 78:
```python
colors = {
    self.STATE_READY: "#ffffff",      # White (was #666666)
    self.STATE_RECORDING: "#66ff66",  # Green (unchanged)
    self.STATE_PROCESSING: "#ffaa00", # Amber (unchanged)
}
```

---

## Issue 1: About Dialog Improvements

**Problem**: Black titlebar, full URL text displayed.

### File: src/cld/daemon_service.py

In `_show_about_dialog()`:

1. Add dark titlebar helper (reuse pattern from settings_dialog.py)
2. Change GitHub link from full URL to "View on GitHub" clickable text
3. Add underline style and hover effect

Key changes:
- Add `_set_dark_title_bar()` method
- Change link label text from URL to "View on GitHub"
- Add font underline and hover color change

---

## Issue 4: Tiny Overlay Redesign (UX Priority)

**Problem**: Current 28x28 gray dot is ugly with no visual appeal or drag handle.

**Inspiration**: Windows Voice Typing - pill-shaped widget with gear/mic/drag icons.

### New Design Specs

```
+----------------------------------------+
|  [gear]  |  [mic icon]  |  [drag |||]  |
+----------------------------------------+
    ~30px       ~60px          ~30px
        Total: ~120px x 40px
```

### File: src/cld/ui/overlay.py

1. Update dimensions:
```python
self._tiny_width = 120   # was _tiny_size = 28
self._tiny_height = 40
```

2. Replace `_build_tiny_ui()` completely with:
   - Gear button on left (opens settings popup)
   - Microphone icon in center (color changes by state, pulse animation for recording)
   - Drag handle on right (3 horizontal lines with fleur cursor)

3. Add `_draw_drag_handle()` method - draws 3 horizontal lines

4. Add `_draw_tiny_mic()` method - draws microphone icon with state-based colors:
   - Ready: #666666 (gray)
   - Recording: #66ff66 (green) with pulse animation
   - Transcribing: #ffaa00 (amber)
   - Error: #ff4444 (red)

5. Update `_switch_to_tiny()` for new dimensions with smooth animation

6. Add smooth transition animation between modes:
   - `_animate_to_size(target_w, target_h, steps=10, duration_ms=150)` method
   - Gradually resize window from current size to target over ~150ms
   - Rebuild UI only after animation completes
   - Makes the tiny->normal and normal->tiny transitions feel polished instead of abrupt

7. Update `_animate()` and `_apply_state()` to handle new tiny mode drawing

---

## Critical Files

| File | Changes |
|------|---------|
| src/cld/ui/overlay.py | Issue 3 (_close), Issue 4 (tiny redesign) |
| src/cld/daemon_service.py | Issue 1 (about dialog), Issue 3 (overlay lifecycle) |
| src/cld/ui/tray.py | Issue 2 (icon color) |

---

## Verification Plan

1. **Issue 3 Test**: Start CLD -> Right-click overlay to close -> Tray "Show Overlay" -> Verify it reappears -> Click Settings -> Verify dialog opens without hang

2. **Issue 2 Test**: Set Windows to dark taskbar -> Start CLD -> Verify white microphone icon visible

3. **Issue 1 Test**: Tray -> About CLD -> Verify dark titlebar, "View on GitHub" clickable link

4. **Issue 4 Test**: Start CLD -> Let overlay collapse to tiny -> Verify pill shape with gear/mic/drag -> Test drag handle moves window -> Test gear opens settings -> Test double-click expands -> Test state colors
