def extract_icon_placeholder(exe_path: str) -> str | None:
    """Placeholder for icon extraction."""
    return None


def extract_icon_to_png(exe_path: str, out_path: str, size: int = 48) -> bool:
    """Extract the best icon from a Windows executable to a transparent PNG.

    This is Windows-only and relies on pywin32 + Pillow. It never executes
    the target executable; it only reads icon resources and writes a PNG.

    Returns True on success, False on failure.
    """

    import sys
    from pathlib import Path

    if sys.platform != "win32":
        return False

    exe = Path(exe_path)
    if not exe.exists():
        return False

    try:
        import win32con  # type: ignore
        import win32gui  # type: ignore
        import win32ui  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        # Icon extraction dependencies not available
        return False

    hicon = None
    extra_icons: list[int] = []

    try:
        large, small = win32gui.ExtractIconEx(str(exe), 0)
        if large:
            hicon = large[0]
            extra_icons.extend(large[1:])
            extra_icons.extend(small)
        elif small:
            hicon = small[0]
            extra_icons.extend(small[1:])

        if not hicon:
            return False

        # Create a device context and bitmap to render the icon into
        hdc = win32ui.CreateDCFromHandle(win32gui.GetDC(0))
        hdc_mem = hdc.CreateCompatibleDC()

        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(hdc, size, size)
        old = hdc_mem.SelectObject(bmp)

        # Draw the icon with alpha onto the bitmap
        win32gui.DrawIconEx(
            hdc_mem.GetHandleOutput(),
            0,
            0,
            hicon,
            size,
            size,
            0,
            None,
            win32con.DI_NORMAL,
        )

        # Convert raw bitmap to RGBA Pillow image
        bmp_info = bmp.GetInfo()
        bmp_bytes = bmp.GetBitmapBits(True)

        width = bmp_info["bmWidth"]
        height = bmp_info["bmHeight"]

        # Windows bitmaps are BGRA; convert to RGBA
        image = Image.frombuffer(
            "RGBA",
            (width, height),
            bmp_bytes,
            "raw",
            "BGRA",
            0,
            1,
        )

        # Resize to requested size
        try:
            resample = Image.Resampling.LANCZOS  # Pillow >= 9
        except AttributeError:  # pragma: no cover - compatibility
            resample = Image.LANCZOS

        image = image.resize((size, size), resample)

        out_file = Path(out_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        image.save(out_file, format="PNG")

        return True
    except Exception:
        return False
    finally:
        # Cleanup GDI resources
        try:
            if "old" in locals():
                hdc_mem.SelectObject(old)
        except Exception:
            pass
        try:
            for hi in extra_icons:
                win32gui.DestroyIcon(hi)
        except Exception:
            pass
        try:
            if hicon:
                win32gui.DestroyIcon(hicon)
        except Exception:
            pass
