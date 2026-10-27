"""AI视频任务工作站的预启动页：只用 tkinter，确保能在 PyQt 完成导入前出现。"""
import json
import os
import sys
import time
import tkinter as tk


def _last_main_window_work_area():
    """Return the saved main-window monitor work area on Windows, if present."""
    if os.name != "nt":
        return None
    try:
        data_dir = os.environ.get("VIDEO_TASK_HUB_DATA_DIR", "").strip() or os.path.join(
            os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.dirname(os.path.abspath(__file__)),
            "VideoTaskHub",
        )
        with open(os.path.join(data_dir, "config.json"), "r", encoding="utf-8") as config_file:
            config = json.load(config_file) or {}
        # Qt's QScreen.name is often a monitor model (for example UDEA...),
        # but EnumDisplayMonitors exposes the Windows device (DISPLAY1/2).
        # Prefer the explicitly saved device id; keep the old field solely for
        # configurations created before this fix.
        screen_name = str(config.get("main_window_monitor_device") or config.get("main_window_screen_name") or "").strip()
        if not screen_name:
            return None
        import ctypes
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32),
            ]

        # Old builds saved a Qt monitor model name instead of DISPLAY1/2.  Map
        # that model through EnumDisplayDevices before looking up its work area.
        # This handles side-by-side monitors even when their virtual coordinates
        # are affected by mixed DPI scaling.
        explicit_device = str(config.get("main_window_monitor_device") or "").strip()
        if not explicit_device and screen_name:
            class DisplayDevice(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                    ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                    ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128),
                ]
            wanted = screen_name.casefold()
            for adapter_index in range(16):
                adapter = DisplayDevice(); adapter.cb = ctypes.sizeof(DisplayDevice)
                if not ctypes.windll.user32.EnumDisplayDevicesW(None, adapter_index, ctypes.byref(adapter), 0):
                    break
                if wanted in str(adapter.DeviceString or "").casefold():
                    explicit_device = str(adapter.DeviceName or "")
                    break
                for monitor_index in range(16):
                    monitor_device = DisplayDevice(); monitor_device.cb = ctypes.sizeof(DisplayDevice)
                    if not ctypes.windll.user32.EnumDisplayDevicesW(adapter.DeviceName, monitor_index, ctypes.byref(monitor_device), 0):
                        break
                    if wanted in str(monitor_device.DeviceString or "").casefold():
                        explicit_device = str(adapter.DeviceName or "")
                        break
                if explicit_device:
                    break
        target = (explicit_device or screen_name).replace("\\\\.\\", "").casefold()
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        def visit(monitor, _dc, _rect, _data):
            info = MonitorInfo(); info.cbSize = ctypes.sizeof(MonitorInfo)
            if ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                if str(info.szDevice or "").replace("\\\\.\\", "").casefold() == target:
                    found.append((info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom))
                    return False
            return True
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, callback_type(visit), 0)
        if found:
            return found[0]
        # One-time compatibility for configurations saved before a Windows
        # DISPLAY id existed: the persisted window geometry still identifies
        # the physical monitor in the virtual desktop, even when Qt's model
        # name cannot be compared with DISPLAY1/2.
        geometry = list(config.get("main_window_geom") or [])
        if len(geometry) == 4:
            try:
                point = wintypes.POINT(int(geometry[0]) + max(1, int(geometry[2])) // 2,
                                      int(geometry[1]) + max(1, int(geometry[3])) // 2)
                monitor = ctypes.windll.user32.MonitorFromPoint(point, 2)
                info = MonitorInfo(); info.cbSize = ctypes.sizeof(MonitorInfo)
                if monitor and ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    return (info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom)
            except Exception:
                pass
        return None
    except Exception:
        return None


def main():
    ready_flag = sys.argv[1] if len(sys.argv) > 1 else ""
    position_file = sys.argv[2] if len(sys.argv) > 2 else ""
    root = tk.Tk()
    root.overrideredirect(True)
    # 预启动窗不强制置顶；用户切换到其它程序时必须可以正常操作其它窗口。
    root.attributes("-topmost", False)
    width, height = 490, 228
    work_area = _last_main_window_work_area()
    if work_area:
        left, top, right, bottom = work_area
        x = left + max(0, ((right - left) - width) // 2)
        y = top + max(0, ((bottom - top) - height) // 2)
    else:
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.configure(bg="#0f172a")

    # 启动页是无边框窗口，必须保留明确的移动方式，避免遮住其他窗口时无法挪开。
    drag_origin = {"x": 0, "y": 0}

    def _current_monitor_info():
        """读取 Windows 实际承载本窗口的显示器，避开 Tk/Qt 的 DPI 坐标差异。"""
        if os.name != "nt":
            return {}
        try:
            import ctypes
            from ctypes import wintypes

            class MonitorInfo(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32),
                ]

            monitor = ctypes.windll.user32.MonitorFromWindow(root.winfo_id(), 2)  # 最近显示器
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if not monitor or not ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return {}
            return {
                "monitor_device": str(info.szDevice or ""),
                "monitor_work": [info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom],
            }
        except Exception:
            return {}

    def _save_position():
        if not position_file:
            return
        try:
            payload = {"x": root.winfo_x(), "y": root.winfo_y()}
            payload.update(_current_monitor_info())
            with open(position_file, "w", encoding="utf-8") as output:
                json.dump(payload, output)
        except OSError:
            pass

    def _start_drag(event):
        drag_origin["x"], drag_origin["y"] = event.x_root, event.y_root

    def _drag_window(event):
        dx, dy = event.x_root - drag_origin["x"], event.y_root - drag_origin["y"]
        if dx or dy:
            root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")
            drag_origin["x"], drag_origin["y"] = event.x_root, event.y_root
            root.after_idle(_save_position)

    frame = tk.Frame(root, bg="#172554", highlightthickness=1, highlightbackground="#3b82f6")
    frame.pack(fill="both", expand=True, padx=1, pady=1)
    mark = tk.Label(frame, text="✦", bg="#172554", fg="#60a5fa", font=("Segoe UI", 30, "bold")); mark.pack(pady=(31, 3))
    title = tk.Label(frame, text="AI视频任务工作站", bg="#172554", fg="#f8fafc", font=("Microsoft YaHei UI", 18, "bold")); title.pack()
    edition = tk.Label(frame, text="AI VIDEO TASK WORKSTATION", bg="#172554", fg="#93c5fd", font=("Segoe UI", 8, "bold")); edition.pack(pady=(2, 0))
    detail = tk.Label(frame, text="正在准备工作区…", bg="#172554", fg="#bfdbfe", font=("Microsoft YaHei UI", 10)); detail.pack(pady=(7, 17))
    bar_shell = tk.Frame(frame, bg="#1e3a5f", height=7)
    bar_shell.pack(fill="x", padx=64)
    bar_shell.pack_propagate(False)
    bar = tk.Frame(bar_shell, bg="#38bdf8", width=150, height=7)
    bar.place(x=0, y=0)

    # bind_all 在某些 Windows/Tk 组合中会被子控件的 class binding 吞掉。
    # 对启动页中每个可见部件直接绑定，确保按住任意位置都能移动窗口。
    def _bind_drag_target(widget):
        widget.bind("<ButtonPress-1>", _start_drag)
        widget.bind("<B1-Motion>", _drag_window)
        # 松开鼠标时同步写入最终位置，避免主程序接替得很快时只读到拖动前的坐标。
        widget.bind("<ButtonRelease-1>", lambda _event: _save_position())

    for drag_target in (root, frame, mark, title, edition, detail, bar_shell, bar):
        _bind_drag_target(drag_target)

    start_time = time.monotonic()
    def poll():
        if ready_flag and os.path.exists(ready_flag):
            try:
                os.remove(ready_flag)
            except OSError:
                pass
            root.destroy()
            return
        # 主程序异常退出时自动收尾，绝不会遗留无响应的小窗口。
        if time.monotonic() - start_time > 35:
            root.destroy()
            return
        progress = int((time.monotonic() * 90) % 290)
        bar.place(x=progress - 145, y=0)
        root.after(45, poll)

    # Tk 刚进入事件循环时 winfo_x/y 仍可能是默认 (0, 0)。等窗口真正映射并
    # 完成初始 geometry 后再记录，未拖动时也能把居中位置准确交给第二启动窗。
    root.after(120, _save_position)
    root.after(0, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
