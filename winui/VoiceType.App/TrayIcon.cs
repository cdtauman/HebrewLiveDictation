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
    private IntPtr _hwnd;
    private Native.NOTIFYICONDATA _nid;
    private bool _added;

    public TrayIcon()
    {
        _wndProc = WndProc;
        IntPtr hInstance = Native.GetModuleHandleW(null);
        var wc = new Native.WNDCLASS { lpfnWndProc = _wndProc, hInstance = hInstance, lpszClassName = _className };
        Native.RegisterClassW(ref wc);
        _hwnd = Native.CreateWindowExW(0, _className, "VoiceTypeTray", 0, 0, 0, 0, 0,
                                       Native.HWND_MESSAGE, IntPtr.Zero, hInstance, IntPtr.Zero);

        _nid = new Native.NOTIFYICONDATA
        {
            cbSize = Marshal.SizeOf<Native.NOTIFYICONDATA>(),
            hWnd = _hwnd,
            uID = 1,
            uFlags = Native.NIF_MESSAGE | Native.NIF_ICON | Native.NIF_TIP,
            uCallbackMessage = (int)CallbackMsg,
            hIcon = Native.LoadIcon(IntPtr.Zero, Native.IDI_APPLICATION),
            szTip = "VoiceType",
        };
        _added = Native.Shell_NotifyIcon(Native.NIM_ADD, ref _nid);
    }

    public bool IsAdded => _added;

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
        if (_hwnd != IntPtr.Zero) { Native.DestroyWindow(_hwnd); _hwnd = IntPtr.Zero; }
    }
}
