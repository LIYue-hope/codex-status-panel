using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

internal static class CodexStatusWatcher
{
    private const uint ProcessQueryLimitedInformation = 0x1000;
    private const int GwlExStyle = -20;
    private const long WsExToolWindow = 0x00000080L;
    private const int DwmwaCloaked = 14;

    private static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
    private static readonly string LogPath = Path.Combine(Root, "watcher.log");
    private static readonly string OverlayPath = Path.Combine(Root, "CodexStatusOverlay.ps1");
    private static readonly Encoding Utf8 = new UTF8Encoding(false);
    private static readonly object LogLock = new object();

    private delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr parameter);

    [StructLayout(LayoutKind.Sequential)]
    private struct Rect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr parameter);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hwnd);

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    private static extern IntPtr GetWindowLongPtr64(IntPtr hwnd, int index);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongW")]
    private static extern IntPtr GetWindowLongPtr32(IntPtr hwnd, int index);

    [DllImport("dwmapi.dll")]
    private static extern int DwmGetWindowAttribute(IntPtr hwnd, int attribute, out int value, int size);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inheritHandle, uint processId);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool QueryFullProcessImageName(IntPtr process, int flags, StringBuilder path, ref int size);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    private static IntPtr GetWindowExStyle(IntPtr hwnd)
    {
        return IntPtr.Size == 8 ? GetWindowLongPtr64(hwnd, GwlExStyle) : GetWindowLongPtr32(hwnd, GwlExStyle);
    }

    private static void Log(string message)
    {
        try
        {
            lock (LogLock)
            {
                File.AppendAllText(LogPath,
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + " " + message + Environment.NewLine,
                    Utf8);
            }
        }
        catch { }
    }

    private static string GetProcessPath(uint processId)
    {
        IntPtr handle = OpenProcess(ProcessQueryLimitedInformation, false, processId);
        if (handle == IntPtr.Zero) return null;
        try
        {
            var path = new StringBuilder(32768);
            int size = path.Capacity;
            return QueryFullProcessImageName(handle, 0, path, ref size) ? path.ToString() : null;
        }
        finally
        {
            CloseHandle(handle);
        }
    }

    private static bool IsCodexExecutable(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        if (!string.Equals(Path.GetFileName(path), "ChatGPT.exe", StringComparison.OrdinalIgnoreCase)) return false;
        return path.IndexOf("OpenAI.Codex_", StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static bool HasVisibleCodexWindow()
    {
        bool found = false;
        var paths = new Dictionary<uint, string>();
        EnumWindows(delegate(IntPtr hwnd, IntPtr unused)
        {
            if (!IsWindowVisible(hwnd)) return true;

            Rect rect;
            if (!GetWindowRect(hwnd, out rect) || rect.Right - rect.Left < 200 || rect.Bottom - rect.Top < 150)
                return true;

            int cloaked;
            if (DwmGetWindowAttribute(hwnd, DwmwaCloaked, out cloaked, sizeof(int)) == 0 && cloaked != 0)
                return true;

            if ((GetWindowExStyle(hwnd).ToInt64() & WsExToolWindow) != 0) return true;

            uint processId;
            GetWindowThreadProcessId(hwnd, out processId);
            string path;
            if (!paths.TryGetValue(processId, out path))
            {
                path = GetProcessPath(processId);
                paths[processId] = path;
            }
            if (!IsCodexExecutable(path)) return true;

            found = true;
            return false;
        }, IntPtr.Zero);
        return found;
    }

    private static string FindPowerShell()
    {
        string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        string bundled = Path.Combine(profile,
            @".cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe");
        if (File.Exists(bundled)) return bundled;

        string system = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
            @"WindowsPowerShell\v1.0\powershell.exe");
        return File.Exists(system) ? system : null;
    }

    private static Process StartOverlay()
    {
        string powershell = FindPowerShell();
        if (powershell == null) throw new FileNotFoundException("未找到 PowerShell。", "pwsh.exe");
        if (!File.Exists(OverlayPath)) throw new FileNotFoundException("未找到悬浮窗脚本。", OverlayPath);

        var startInfo = new ProcessStartInfo
        {
            FileName = powershell,
            Arguments = "-NoProfile -STA -WindowStyle Hidden -File \"" + OverlayPath + "\"",
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Root
        };
        return Process.Start(startInfo);
    }

    private static bool HasExited(Process process)
    {
        if (process == null) return true;
        try
        {
            process.Refresh();
            return process.HasExited;
        }
        catch { return true; }
    }

    private static void StopOverlay(Process process)
    {
        if (process == null || HasExited(process)) return;
        try
        {
            process.Kill();
            process.WaitForExit(3000);
        }
        catch (Exception ex)
        {
            Log("关闭悬浮窗失败：" + ex.Message);
        }
    }

    [STAThread]
    private static int Main()
    {
        bool createdNew;
        using (var mutex = new Mutex(true, @"Local\CodexStatusOverlayWatcherExe", out createdNew))
        {
            if (!createdNew) return 0;

            Process overlay = null;
            bool wasVisible = false;
            bool suppressedForSession = false;
            Log("EXE 监视器启动，PID=" + Process.GetCurrentProcess().Id);

            try
            {
                while (true)
                {
                    bool visible = false;
                    try
                    {
                        visible = HasVisibleCodexWindow();

                        if (visible && !wasVisible)
                        {
                            suppressedForSession = false;
                            overlay = StartOverlay();
                            Log("检测到 Codex 可见主窗口，启动悬浮窗 PID=" + overlay.Id);
                        }
                        else if (!visible && wasVisible)
                        {
                            StopOverlay(overlay);
                            overlay = null;
                            suppressedForSession = false;
                            Log("Codex 主窗口已关闭，悬浮窗已关闭。");
                        }
                        else if (visible && overlay != null && HasExited(overlay))
                        {
                            Log("悬浮窗已手动关闭，本次 Codex 窗口会话不再重启。");
                            overlay.Dispose();
                            overlay = null;
                            suppressedForSession = true;
                        }
                        else if (visible && overlay == null && !suppressedForSession)
                        {
                            overlay = StartOverlay();
                            Log("悬浮窗进程缺失，已重新启动 PID=" + overlay.Id);
                        }

                        wasVisible = visible;
                    }
                    catch (Exception ex)
                    {
                        Log("监视循环错误：" + ex.Message);
                    }
                    Thread.Sleep(1000);
                }
            }
            finally
            {
                StopOverlay(overlay);
                Log("EXE 监视器停止。");
                try { mutex.ReleaseMutex(); } catch { }
            }
        }
    }
}
