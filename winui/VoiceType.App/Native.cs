using System;
using System.Runtime.InteropServices;
using System.Text;

namespace VoiceType.Shell;

/// <summary>
/// Win32 interop for the Phase-1 migration proofs: no-activate / click-through /
/// always-on-top overlay styling (focus-safety), foreground-window queries,
/// tray icon (Shell_NotifyIcon), DPI and multi-monitor info.
/// </summary>
internal static class Native
{
    public const int GWL_EXSTYLE = -20;
    public const long WS_EX_NOACTIVATE = 0x08000000;
    public const long WS_EX_TRANSPARENT = 0x00000020;
    public const long WS_EX_LAYERED = 0x00080000;
    public const long WS_EX_TOPMOST = 0x00000008;
    public const long WS_EX_TOOLWINDOW = 0x00000080;

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    public static string GetWindowTitle(IntPtr hWnd)
    {
        var sb = new StringBuilder(512);
        GetWindowTextW(hWnd, sb, sb.Capacity);
        return sb.ToString();
    }

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW", SetLastError = true)]
    private static extern IntPtr GetWindowLongPtr(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)]
    private static extern IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

    public static long GetExStyle(IntPtr hWnd) => GetWindowLongPtr(hWnd, GWL_EXSTYLE).ToInt64();

    /// <summary>Apply overlay extended styles. clickThrough adds WS_EX_TRANSPARENT (HUD only).</summary>
    public static void MakeOverlay(IntPtr hWnd, bool clickThrough)
    {
        long ex = GetExStyle(hWnd);
        ex |= WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED;
        if (clickThrough)
            ex |= WS_EX_TRANSPARENT;
        SetWindowLongPtr(hWnd, GWL_EXSTYLE, new IntPtr(ex));
    }

    // ---- DPI ----------------------------------------------------------------
    [DllImport("user32.dll")]
    public static extern uint GetDpiForWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr GetThreadDpiAwarenessContext();

    [DllImport("user32.dll")]
    public static extern int GetAwarenessFromDpiAwarenessContext(IntPtr context);
    // DPI_AWARENESS: Invalid=-1, Unaware=0, System=1, PerMonitor=2

    // ---- Monitors -----------------------------------------------------------
    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);
    public const int SM_CMONITORS = 80;
    public const int SM_CXVIRTUALSCREEN = 78;
    public const int SM_CYVIRTUALSCREEN = 79;

    // ---- Tray (Shell_NotifyIcon) -------------------------------------------
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct NOTIFYICONDATA
    {
        public int cbSize;
        public IntPtr hWnd;
        public int uID;
        public int uFlags;
        public int uCallbackMessage;
        public IntPtr hIcon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
        public string szTip;
    }

    public const int NIM_ADD = 0x0;
    public const int NIM_DELETE = 0x2;
    public const int NIF_ICON = 0x2;
    public const int NIF_MESSAGE = 0x1;
    public const int NIF_TIP = 0x4;

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern bool Shell_NotifyIcon(int dwMessage, ref NOTIFYICONDATA lpData);

    [DllImport("user32.dll")]
    public static extern IntPtr LoadIcon(IntPtr hInstance, IntPtr lpIconName);
    public static readonly IntPtr IDI_APPLICATION = new IntPtr(32512);

    [DllImport("kernel32.dll")]
    public static extern IntPtr GetModuleHandleW(string? lpModuleName);

    // ---- Message-only window + WndProc (for tray callbacks) -----------------
    public delegate IntPtr WndProcDelegate(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct WNDCLASS
    {
        public uint style;
        public WndProcDelegate lpfnWndProc;
        public int cbClsExtra;
        public int cbWndExtra;
        public IntPtr hInstance;
        public IntPtr hIcon;
        public IntPtr hCursor;
        public IntPtr hbrBackground;
        public string? lpszMenuName;
        public string lpszClassName;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int x; public int y; }

    public static readonly IntPtr HWND_MESSAGE = new IntPtr(-3);
    public const uint WM_APP = 0x8000;
    public const uint WM_NULL = 0x0000;
    public const uint WM_LBUTTONUP = 0x0202;
    public const uint WM_LBUTTONDBLCLK = 0x0203;
    public const uint WM_RBUTTONUP = 0x0205;
    public const uint WM_CONTEXTMENU = 0x007B;
    public const uint WM_NCLBUTTONDOWN = 0x00A1;
    public const int HTCAPTION = 2;
    public const int NIF_MESSAGE_FLAG = 0x1;

    public const uint MF_STRING = 0x0;
    public const uint MF_SEPARATOR = 0x800;
    public const uint TPM_RIGHTBUTTON = 0x0002;
    public const uint TPM_RETURNCMD = 0x0100;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern ushort RegisterClassW(ref WNDCLASS lpWndClass);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr CreateWindowExW(int dwExStyle, string lpClassName, string? lpWindowName,
        int dwStyle, int x, int y, int w, int h, IntPtr parent, IntPtr menu, IntPtr hInstance, IntPtr lpParam);

    [DllImport("user32.dll")]
    public static extern IntPtr DefWindowProcW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool DestroyWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern IntPtr CreatePopupMenu();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool AppendMenuW(IntPtr hMenu, uint uFlags, uint uIDNewItem, string? lpNewItem);
    [DllImport("user32.dll")]
    public static extern int TrackPopupMenuEx(IntPtr hMenu, uint uFlags, int x, int y, IntPtr hwnd, IntPtr lptpm);
    [DllImport("user32.dll")]
    public static extern bool DestroyMenu(IntPtr hMenu);
    [DllImport("user32.dll")]
    public static extern bool GetCursorPos(out POINT lpPoint);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool PostMessageW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    // ---- Drag a frameless window (Remote) -----------------------------------
    [DllImport("user32.dll")]
    public static extern bool ReleaseCapture();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr SendMessageW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    public static int LoWord(IntPtr v) => unchecked((short)(v.ToInt64() & 0xFFFF));
}
