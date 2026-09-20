using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using Accessibility;

internal static class GetActiveCodexTitle
{
    private const int MaxDepth = 32;
    private const int MaxVisitedNodes = 12000;
    private static int visitedNodes;

    [DllImport("oleacc.dll")]
    private static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint id, ref Guid iid,
        [In, Out, MarshalAs(UnmanagedType.IUnknown)] ref object accessible);

    [DllImport("oleacc.dll")]
    private static extern int AccessibleChildren(IAccessible container, int start, int count,
        [Out, MarshalAs(UnmanagedType.LPArray, SizeParamIndex = 2)] object[] children, out int obtained);

    private static string ReadName(IAccessible accessible, object childId)
    {
        try { return (accessible.accName[childId] ?? string.Empty).Trim(); }
        catch { return string.Empty; }
    }

    private static int ReadRole(IAccessible accessible, object childId)
    {
        try { return Convert.ToInt32(accessible.accRole[childId]); }
        catch { return 0; }
    }

    private static string FindTitle(IAccessible accessible, int depth)
    {
        if (depth > MaxDepth || ++visitedNodes > MaxVisitedNodes) return null;
        string ownName = ReadName(accessible, 0);
        // Chromium exposes the active Codex task heading as ROLE_SYSTEM_PANE (15).
        if (ReadRole(accessible, 0) == 15 && !string.IsNullOrWhiteSpace(ownName)) return ownName;

        int count;
        try { count = accessible.accChildCount; } catch { return null; }
        if (count <= 0 || count > 5000) return null;
        object[] children = new object[count];
        int obtained;
        if (AccessibleChildren(accessible, 0, count, children, out obtained) != 0) return null;
        for (int i = 0; i < obtained; i++)
        {
            IAccessible nested = children[i] as IAccessible;
            if (nested != null)
            {
                string match = FindTitle(nested, depth + 1);
                if (!string.IsNullOrEmpty(match)) return match;
                continue;
            }

            // AccessibleChildren may return a CHILDID_SELF-relative integer
            // instead of another IAccessible COM object. The old helper
            // discarded these nodes, which made active-task detection fail on
            // newer Codex/Chromium accessibility trees.
            object childId = children[i];
            string childName = ReadName(accessible, childId);
            if (ReadRole(accessible, childId) == 15 && !string.IsNullOrWhiteSpace(childName))
                return childName;
        }
        return null;
    }

    public static int Main()
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        IntPtr hwnd = IntPtr.Zero;
        foreach (Process process in Process.GetProcessesByName("ChatGPT"))
        {
            if (process.MainWindowHandle != IntPtr.Zero)
            {
                hwnd = process.MainWindowHandle;
                break;
            }
        }
        if (hwnd == IntPtr.Zero) return 2;

        Guid iid = new Guid("618736e0-3c3d-11cf-810c-00aa00389b71");
        object value = null;
        if (AccessibleObjectFromWindow(hwnd, 0xFFFFFFFC, ref iid, ref value) != 0 || value == null) return 3;
        visitedNodes = 0;
        string title = FindTitle((IAccessible)value, 0);
        if (string.IsNullOrWhiteSpace(title)) return 4;
        Console.Write(title);
        return 0;
    }
}
