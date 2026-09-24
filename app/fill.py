# -*- coding: utf-8 -*-
"""把候选写进微信输入框。默认只填入；自动发送必须由调用方显式开启，并可要求微信仍是前台窗口。"""
import ctypes
import ctypes.wintypes as w
import time

u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32

# 64 位下 ctypes.windll 默认 restype 是 32 位 c_int，而 GlobalAlloc 返回 64 位 HGLOBAL——
# 不声明类型句柄会被截断成垃圾值，GlobalLock(垃圾) 返回 NULL，memmove(NULL,…) 就是
# "access violation writing 0x0"。所有带句柄/指针的函数必须显式声明。
k32.GlobalAlloc.restype = ctypes.c_void_p
k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalLock.argtypes = [ctypes.c_void_p]
k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
k32.GlobalFree.argtypes = [ctypes.c_void_p]
u32.SetClipboardData.restype = ctypes.c_void_p
u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]


def set_clipboard(text):
    """写剪贴板。剪贴板可能被别的程序占着（剪贴板管理器、截图工具），重试几次。"""
    data = text.encode("utf-16-le") + b"\0\0"
    for attempt in range(10):
        if not u32.OpenClipboard(None):
            time.sleep(0.05)
            continue
        try:
            u32.EmptyClipboard()
            h = k32.GlobalAlloc(0x2, len(data))  # GMEM_MOVEABLE
            if not h:
                raise RuntimeError("GlobalAlloc 失败")
            p = k32.GlobalLock(h)
            if not p:
                k32.GlobalFree(h)
                raise RuntimeError("GlobalLock 失败")
            ctypes.memmove(p, data, len(data))
            k32.GlobalUnlock(h)
            if not u32.SetClipboardData(13, h):  # CF_UNICODETEXT；成功后句柄归系统，不能 Free
                k32.GlobalFree(h)
                raise RuntimeError(f"SetClipboardData 失败 (attempt {attempt})")
            return
        finally:
            u32.CloseClipboard()
    raise RuntimeError("OpenClipboard 连续失败，剪贴板被其他程序占用")


def is_foreground(hwnd):
    """只有目标微信主窗口本身是系统当前前台窗口才算通过。"""
    return bool(hwnd and u32.GetForegroundWindow() == hwnd)


def fill(hwnd, area, text, *, send=False, require_foreground=False):
    """area = 消息区 (x0, y0, x1, y1)；输入框就在底线 y1 下面。

    send=False 保持原行为，只填入不发送。
    require_foreground=True 时绝不抢焦点：只要微信不是当前前台窗口就立即取消。
    """
    from app.capture import unminimize

    if require_foreground and not is_foreground(hwnd):
        raise RuntimeError("自动发送已取消：微信不是当前前台窗口")

    set_clipboard(text)
    r = w.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:  # 扩展边界，跟 WGC 帧对齐
        u32.GetWindowRect(hwnd, ctypes.byref(r))
    x0, _, _, y1 = area
    cx, cy = r.left + x0 + 60, r.top + y1 + 40  # 分隔线下 40px = 输入框文字区；工具栏和「发送」在输入区最底下，碰不到
    if require_foreground:
        # 自动发送不能帮用户切窗口；检查失败就保持候选在界面里，交给用户手动处理。
        if not is_foreground(hwnd):
            raise RuntimeError("自动发送已取消：微信不再是当前前台窗口")
    else:
        unminimize(hwnd)

    # 手动“填入微信”沿用原来的抢焦点行为；自动发送路径绝不走这里。
    fg = u32.GetForegroundWindow()
    if fg != hwnd:
        if require_foreground:
            raise RuntimeError("自动发送已取消：微信不再是当前前台窗口")
        fg_tid = u32.GetWindowThreadProcessId(fg, None)
        our_tid = k32.GetCurrentThreadId()
        u32.AttachThreadInput(our_tid, fg_tid, True)
        u32.SetForegroundWindow(hwnd)
        u32.AttachThreadInput(our_tid, fg_tid, False)
        time.sleep(0.15)  # 给微信一点时间响应前台切换

    old = w.POINT()
    u32.GetCursorPos(ctypes.byref(old))
    u32.SetCursorPos(cx, cy)
    time.sleep(0.05)
    u32.mouse_event(0x2, 0, 0, 0, 0)  # 左键按下
    u32.mouse_event(0x4, 0, 0, 0, 0)  # 抬起
    time.sleep(0.05)
    u32.SetCursorPos(old.x, old.y)
    time.sleep(0.05)
    # 光标移到已有文本的绝对末尾：点击落在文字中间时 caret 会插在中间，
    # 连续多次填入就串行错乱；Ctrl+End 保证新内容永远追加在最后
    u32.keybd_event(0x11, 0, 0, 0)  # Ctrl 按下
    u32.keybd_event(0x23, 0, 0, 0)  # End 按下（VK_END）
    u32.keybd_event(0x23, 0, 2, 0)  # End 抬起
    u32.keybd_event(0x11, 0, 2, 0)  # Ctrl 抬起
    time.sleep(0.05)
    u32.keybd_event(0x11, 0, 0, 0)  # Ctrl
    u32.keybd_event(0x56, 0, 0, 0)  # V
    u32.keybd_event(0x56, 0, 2, 0)
    u32.keybd_event(0x11, 0, 2, 0)

    if not send:
        return

    # 自动发送最后一道闸门：粘贴完成后再确认一次前台窗口，避免用户在这几十毫秒里切走。
    if require_foreground and not is_foreground(hwnd):
        raise RuntimeError("自动发送已取消：粘贴后微信失去前台焦点，内容已填入但没有发送")
    time.sleep(0.08)
    u32.keybd_event(0x0D, 0, 0, 0)  # Enter
    u32.keybd_event(0x0D, 0, 2, 0)
