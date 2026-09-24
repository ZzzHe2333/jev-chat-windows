# -*- coding: utf-8 -*-
"""把候选写进微信输入框。默认只填入；自动发送可短暂激活微信，完成后尽量恢复原前台窗口。"""
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
    """目标微信主窗口是否就是系统当前前台窗口。"""
    return bool(hwnd and u32.GetForegroundWindow() == hwnd)


def _focus_window(hwnd):
    """把 hwnd 临时拉到前台，返回之前的前台窗口。Windows 限制前台切换，借当前前台线程放行。"""
    from app.capture import unminimize

    if not hwnd or not u32.IsWindow(hwnd):
        raise RuntimeError("微信窗口已失效")
    previous = u32.GetForegroundWindow()
    unminimize(hwnd)
    if previous == hwnd:
        return previous

    our_tid = k32.GetCurrentThreadId()
    fg_tid = u32.GetWindowThreadProcessId(previous, None) if previous else 0
    attached = bool(fg_tid and fg_tid != our_tid and u32.AttachThreadInput(our_tid, fg_tid, True))
    try:
        u32.BringWindowToTop(hwnd)
        u32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            u32.AttachThreadInput(our_tid, fg_tid, False)
    time.sleep(0.12)
    if not is_foreground(hwnd):
        raise RuntimeError("无法临时激活微信窗口")
    return previous


def _restore_window(previous, owned_hwnd):
    """仅当焦点仍是我们刚激活的微信时才恢复，避免覆盖用户中途主动切到的新窗口。"""
    if not previous or previous == owned_hwnd or not u32.IsWindow(previous):
        return
    if u32.GetForegroundWindow() != owned_hwnd:
        return
    our_tid = k32.GetCurrentThreadId()
    cur_tid = u32.GetWindowThreadProcessId(owned_hwnd, None)
    attached = bool(cur_tid and cur_tid != our_tid and u32.AttachThreadInput(our_tid, cur_tid, True))
    try:
        u32.SetForegroundWindow(previous)
    finally:
        if attached:
            u32.AttachThreadInput(our_tid, cur_tid, False)


def _window_rect(hwnd):
    r = w.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        u32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def click_window_point(hwnd, x, y, *, restore_after=True):
    """点击 WGC 帧坐标中的一个点。用于后台巡检切换左侧白名单会话。"""
    previous = _focus_window(hwnd)
    try:
        r = _window_rect(hwnd)
        old = w.POINT()
        u32.GetCursorPos(ctypes.byref(old))
        u32.SetCursorPos(r.left + int(x), r.top + int(y))
        time.sleep(0.04)
        u32.mouse_event(0x2, 0, 0, 0, 0)
        u32.mouse_event(0x4, 0, 0, 0, 0)
        time.sleep(0.08)
        u32.SetCursorPos(old.x, old.y)
    finally:
        if restore_after:
            _restore_window(previous, hwnd)


def fill(hwnd, area, text, *, send=False, require_foreground=False, temporary_focus=False):
    """area = 消息区 (x0, y0, x1, y1)；输入框就在底线 y1 下面。

    send=False：只填入，不发送。
    require_foreground=True：保持旧的严格模式，微信不是前台就取消。
    temporary_focus=True：允许短暂激活微信完成操作，结束后尽量恢复之前的前台窗口。
    """
    from app.capture import unminimize

    if require_foreground and not is_foreground(hwnd):
        raise RuntimeError("自动发送已取消：微信不是当前前台窗口")

    set_clipboard(text)
    previous = u32.GetForegroundWindow()
    if temporary_focus:
        previous = _focus_window(hwnd)
    else:
        unminimize(hwnd)
        if not is_foreground(hwnd):
            # 手动“填入微信”沿用原来的抢焦点行为，不恢复。
            _focus_window(hwnd)

    try:
        if not is_foreground(hwnd):
            raise RuntimeError("微信没有获得输入焦点")

        r = _window_rect(hwnd)
        x0, _, _, y1 = area
        cx, cy = r.left + x0 + 60, r.top + y1 + 40

        old = w.POINT()
        u32.GetCursorPos(ctypes.byref(old))
        u32.SetCursorPos(cx, cy)
        time.sleep(0.05)
        u32.mouse_event(0x2, 0, 0, 0, 0)
        u32.mouse_event(0x4, 0, 0, 0, 0)
        time.sleep(0.05)
        u32.SetCursorPos(old.x, old.y)
        time.sleep(0.05)

        # 点击可能落在已有文本中间，先 Ctrl+End，再追加候选。
        u32.keybd_event(0x11, 0, 0, 0)
        u32.keybd_event(0x23, 0, 0, 0)
        u32.keybd_event(0x23, 0, 2, 0)
        u32.keybd_event(0x11, 0, 2, 0)
        time.sleep(0.05)
        u32.keybd_event(0x11, 0, 0, 0)
        u32.keybd_event(0x56, 0, 0, 0)
        u32.keybd_event(0x56, 0, 2, 0)
        u32.keybd_event(0x11, 0, 2, 0)

        if not send:
            return

        # 最后一道闸门：真正按 Enter 前目标微信必须仍在前台。
        if not is_foreground(hwnd):
            raise RuntimeError("自动发送已取消：粘贴后微信失去焦点，内容已填入但没有发送")
        time.sleep(0.08)
        u32.keybd_event(0x0D, 0, 0, 0)
        u32.keybd_event(0x0D, 0, 2, 0)
    finally:
        if temporary_focus:
            _restore_window(previous, hwnd)
