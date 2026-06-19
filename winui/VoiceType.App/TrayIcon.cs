using System;
using System.Runtime.InteropServices;

namespace VoiceType.Shell;

/// <summary>
/// Real Windows tray icon for the WinUI shell: a message-only window receives
/// Shell_NotifyIcon callbacks (left-click = show, right-click = context menu).
/// Must be created on the UI thread so the WinUI message loop dispatches its WndProc.
/// </summary>
public sealed class TrayIcon : IDisposable
{
    private const uint CallbackMsg = Native.WM_APP + 1;

    public event Action? ShowRequested;
    public event Action? StartRequested;
    public event Action? StopRequested;
    public event Action? ExitRequested;

    private readonly Native.WndProcDelegate _wndProc;  // keep alive (no GC)
    private readonly string _className = "VoiceTypeTray_" + Guid.NewGuid().ToString("N");
    private readonly uint _taskbarCreated;             // "TaskbarCreated" broadcast (Explorer restart)
    private IntPtr _hwnd;
    private Native.NOTIFYICONDATA _nid;
    private IntPtr _icon;                               // owned health-orb HICON (must be destroyed)
    private bool _added;
    private string _state = "connecting";

    public TrayIcon()
    {
        _wndProc = WndProc;
        _taskbarCreated = Native.RegisterWindowMessageW("TaskbarCreated");
        IntPtr hInstance = Native.GetModuleHandleW(null);
        var wc = new Native.WNDCLASS { lpfnWndProc = _wndProc, hInstance = hInstance, lpszClassName = _className };
        Native.RegisterClassW(ref wc);
        // A hidden *top-level* window (parent = NULL), NOT a message-only (HWND_MESSAGE)
        // window: only top-level windows receive the "TaskbarCreated" broadcast, which we
        // need to re-add the icon after an Explorer restart. It is never shown.
        _hwnd = Native.CreateWindowExW(0, _className, "VoiceTypeTray", 0, 0, 0, 0, 0,
                                       IntPtr.Zero, IntPtr.Zero, hInstance, IntPtr.Zero);

        var (r, g, b, tip) = Visuals(_state);
        _icon = Native.CreateDotIcon(r, g, b);
        _nid = new Native.NOTIFYICONDATA
        {
            cbSize = Marshal.SizeOf<Native.NOTIFYICONDATA>(),
            hWnd = _hwnd,
            uID = 1,
            uFlags = Native.NIF_MESSAGE | Native.NIF_ICON | Native.NIF_TIP,
            uCallbackMessage = (int)CallbackMsg,
            hIcon = _icon != IntPtr.Zero ? _icon : Native.LoadIcon(IntPtr.Zero, Native.IDI_APPLICATION),
            szTip = tip,
        };
        _added = Native.Shell_NotifyIcon(Native.NIM_ADD, ref _nid);
    }

    public bool IsAdded => _added;

    /// <summary>The tray orb mirrors engine state — the same status symbol the console
    /// and HUD use — so health is glanceable without opening the window.</summary>
    public void SetHealth(string state)
    {
        state = string.IsNullOrEmpty(state) ? "idle" : state;
        if (state == _state) return;
        var (r, g, b, tip) = Visuals(state);
        IntPtr fresh = Native.CreateDotIcon(r, g, b);
        if (fresh == IntPtr.Zero) return;   // keep the current icon + state; retry on next change
        _state = state;
        IntPtr old = _icon;
        _icon = fresh;
        _nid.hIcon = fresh;
        _nid.szTip = tip;
        if (_added) Native.Shell_NotifyIcon(Native.NIM_MODIFY, ref _nid);
        if (old != IntPtr.Zero) Native.DestroyIcon(old);
    }

    /// <summary>State → orb color + tooltip. Color comes from the one shared
    /// <see cref="Palette"/> source (dark-theme semantic values) — no duplicated bytes.</summary>
    private static (byte r, byte g, byte b, string tip) Visuals(string state)
    {
        var c = state switch
        {
            "listening" => Palette.Accent(true).Color,
            "stopping" => Palette.Attention(true).Color,
            "error" or "disconnected" => Palette.Error(true).Color,
            "connecting" => Palette.Neutral(true).Color,
            _ => Palette.Ready(true).Color,
        };
        string tip = state switch
        {
            "listening" => "VoiceType · מקשיב",
            "stopping" => "VoiceType · כותב…",
            "error" => "VoiceType · שגיאה",
            "disconnected" => "VoiceType · המנוע אינו פעיל",
            "connecting" => "VoiceType · מתחבר…",
            _ => "VoiceType · מוכן",
        };
        return (c.R, c.G, c.B, tip);
    }

    private IntPtr WndProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        if (msg == CallbackMsg)
        {
            uint mouse = (uint)Native.LoWord(lParam);
            if (mouse == Native.WM_LBUTTONUP || mouse == Native.WM_LBUTTONDBLCLK)
                ShowRequested?.Invoke();
            else if (mouse == Native.WM_RBUTTONUP || mouse == Native.WM_CONTEXTMENU)
                ShowMenu();
            return IntPtr.Zero;
        }
        // Explorer restarted: re-add the icon (otherwise it silently disappears).
        if (msg == _taskbarCreated && _taskbarCreated != 0)
        {
            _added = Native.Shell_NotifyIcon(Native.NIM_ADD, ref _nid);
            return IntPtr.Zero;
        }
        return Native.DefWindowProcW(hWnd, msg, wParam, lParam);
    }

    private void ShowMenu()
    {
        Native.SetForegroundWindow(_hwnd);
        Native.GetCursorPos(out var pt);
        IntPtr menu = Native.CreatePopupMenu();
        Native.AppendMenuW(menu, Native.MF_STRING, 1, "הצג / Show");
        Native.AppendMenuW(menu, Native.MF_SEPARATOR, 0, null);
        Native.AppendMenuW(menu, Native.MF_STRING, 2, "התחל הכתבה / Start");
        Native.AppendMenuW(menu, Native.MF_STRING, 3, "עצור / Stop");
        Native.AppendMenuW(menu, Native.MF_SEPARATOR, 0, null);
        Native.AppendMenuW(menu, Native.MF_STRING, 4, "יציאה / Exit");
        int cmd = Native.TrackPopupMenuEx(menu, Native.TPM_RIGHTBUTTON | Native.TPM_RETURNCMD,
                                          pt.x, pt.y, _hwnd, IntPtr.Zero);
        Native.DestroyMenu(menu);
        Native.PostMessageW(_hwnd, Native.WM_NULL, IntPtr.Zero, IntPtr.Zero);
        switch (cmd)
        {
            case 1: ShowRequested?.Invoke(); break;
            case 2: StartRequested?.Invoke(); break;
            case 3: StopRequested?.Invoke(); break;
            case 4: ExitRequested?.Invoke(); break;
        }
    }

    public void Dispose()
    {
        if (_added) { Native.Shell_NotifyIcon(Native.NIM_DELETE, ref _nid); _added = false; }
        if (_icon != IntPtr.Zero) { Native.DestroyIcon(_icon); _icon = IntPtr.Zero; }
        if (_hwnd != IntPtr.Zero) { Native.DestroyWindow(_hwnd); _hwnd = IntPtr.Zero; }
    }
}
