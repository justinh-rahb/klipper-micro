"""MicroPython boot script — runs before main.py on every power-on/reset.

Keep this file minimal and dependency-free: a crash here leaves the device
unresponsive until it is reflashed.
"""
import gc

# Raise the GC collection threshold so that LVGL's large pixel-buffer
# allocations do not trigger collections mid-frame.  50 kB gives headroom
# for the 320×240 RGB565 framebuffer (~150 kB) without starving the heap.
gc.threshold(50_000)
