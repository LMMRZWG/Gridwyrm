"""Optional Pillow support for preview images."""

# Pillow is never required. When it happens to be installed, preview images are
# resized smoothly and JPEG works as well as PNG; without it Tk handles PNG and
# GIF on its own, which is enough. Keeping it optional is what lets the packaged
# build stay small and dependency-free.
try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except Exception:
    Image = ImageTk = None
    HAVE_PIL = False
