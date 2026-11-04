"""Map Qt logical desktop coordinates to MSS physical pixels."""
def physical_region(region, screens, monitors):
    left, top = region["left"], region["top"]
    right, bottom = left + region["width"], top + region["height"]
    for screen in screens:
        geometry = screen.geometry()
        if (geometry.x() <= left < right <= geometry.x() + geometry.width()
                and geometry.y() <= top < bottom <= geometry.y() + geometry.height()):
            ratio = screen.devicePixelRatio()
            # Qt and MSS enumerate monitors independently. Match physical origins
            # first and reject ambiguity instead of silently using the wrong screen.
            candidates = [monitor for monitor in monitors if
                          abs(monitor["width"] - geometry.width() * ratio) <= 2
                          and abs(monitor["height"] - geometry.height() * ratio) <= 2]
            exact = [monitor for monitor in candidates if
                     monitor["left"] == geometry.x() and monitor["top"] == geometry.y()]
            if len(exact) == 1:
                monitor = exact[0]
            elif len(candidates) == 1:
                monitor = candidates[0]
            else:
                raise ValueError("无法确定显示器对应关系，请使用主屏或相同缩放比例后重新框选")
            return {
                "left": monitor["left"] + round((left - geometry.x()) * ratio),
                "top": monitor["top"] + round((top - geometry.y()) * ratio),
                "width": round(region["width"] * ratio),
                "height": round(region["height"] * ratio),
            }
    raise ValueError("捕获区域必须位于同一显示器内，请重新框选")
