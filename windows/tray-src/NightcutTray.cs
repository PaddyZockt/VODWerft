using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class NightcutTray
{
    private static readonly DateTime Epoch = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);

    private const string Product = "VODWerft";
    private static string appDir;
    private static string version = "";
    private static string dataDir;
    private static FileStream trayLock; // haelt tray.lock, solange der Tray laeuft

    [STAThread]
    private static int Main(string[] args)
    {
        // Alter Aufruf (Status-Datei + Symbol als Argumente) bleibt moeglich; sonst Pfade selbst bestimmen.
        // Programm liegt in <app>\tray\, Daten in %LOCALAPPDATA%\<Produkt>.
        appDir = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".."));
        try { version = " " + File.ReadAllText(Path.Combine(appDir, "VERSION")).Trim(); } catch { }
        dataDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), Product);
        if (args.Length == 2 && args[0] != "--tray")
        {
            // Altes Verhalten
        }
        else if (args.Length <= 1)
        {
            var icons = Directory.GetFiles(appDir, "*.ico");
            if (icons.Length == 0) return 3;
            args = new[] { Path.Combine(dataDir, "production", "tray-status.json"), icons[0] };
        }
        else return 2;
        bool first;
        using (var single = new System.Threading.Mutex(true, "Local\\" + Product + "-Tray", out first))
        {
            if (!first) return 0;
            // Sperrdatei: das Dashboard erkennt daran, dass ein Tray laeuft (X versteckt das Fenster dann nur)
            try
            {
                var production = Path.Combine(dataDir, "production");
                Directory.CreateDirectory(production);
                trayLock = new FileStream(Path.Combine(production, "tray.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            }
            catch { }
            return Run(args);
        }
    }

    private static int Run(string[] args)
    {
        Application.EnableVisualStyles();
        using (var context = new ApplicationContext())
        using (var icon = new Icon(args[1]))
        using (var tray = new NotifyIcon())
        using (var menu = new ContextMenuStrip())
        using (var timer = new Timer())
        {
            var status = menu.Items.Add("Status wird geladen");
            status.Enabled = false;
            var source = menu.Items.Add("");
            source.Enabled = false;
            source.Visible = false;
            menu.Items.Add(new ToolStripSeparator());
            var header = menu.Items.Add(Product + version);
            header.Enabled = false;
            menu.Items.Add(Product + " öffnen", null, delegate { OpenDashboard(); });
            menu.Items.Add("Einstellungen", null, delegate { StartScript("settings_window.py", Path.Combine(dataDir, "production")); });
            menu.Items.Add("Einrichtung öffnen", null, delegate { StartScript("setup_wizard.py"); });
            menu.Items.Add("Datenordner öffnen", null, delegate { OpenFolder(dataDir); });
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("Beenden", null, delegate
            {
                WriteFlag("dashboard-quit.flag"); // offenes oder verstecktes Dashboard mit beenden
                context.ExitThread();
            });
            tray.Icon = icon;
            tray.ContextMenuStrip = menu;
            // Wie bei Steam: ein Linksklick oeffnet das Fenster oder holt es nach vorn
            tray.MouseClick += delegate (object sender, MouseEventArgs e) { if (e.Button == MouseButtons.Left) OpenDashboard(); };
            var json = new JavaScriptSerializer();
            Action update = delegate
            {
                var data = ReadStatus(json, args[0]);
                var detail = data.ContainsKey("detail") ? Convert.ToString(data["detail"]) : "Statusdienst antwortet nicht";
                status.Text = detail;
                source.Text = data.ContainsKey("source") ? Convert.ToString(data["source"]) : "";
                source.Visible = source.Text.Length > 0;
                var tooltip = Product + version + "\n" + detail;
                if (tooltip.Length > 63) tooltip = tooltip.Substring(0, 62) + "…";
                if (tray.Text != tooltip) tray.Text = tooltip;
            };
            timer.Interval = 5000;
            timer.Tick += delegate { update(); };
            update();
            tray.Visible = true;
            // Erster Start ohne Einrichtung: Assistent von selbst oeffnen
            if (!File.Exists(Path.Combine(dataDir, "production", "watcher.json"))) StartScript("setup_wizard.py");
            timer.Start();
            Application.Run(context);
            tray.Visible = false;
        }
        return 0;
    }

    private static string Python()
    {
        var path = Path.Combine(appDir, "venv", "Scripts", "pythonw.exe");
        return File.Exists(path) ? path : null;
    }

    private static void StartScript(string name, string argument = null)
    {
        var python = Python();
        var script = Path.Combine(appDir, "vodwerft", name);
        if (python == null || !File.Exists(script))
        {
            MessageBox.Show("Programmdatei nicht gefunden:\n" + script, Product, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        Process.Start(new ProcessStartInfo(python, "-X utf8 -B \"" + script + "\"" + (argument == null ? "" : " \"" + argument + "\""))
            { WorkingDirectory = Path.GetDirectoryName(script), UseShellExecute = false });
    }

    private static void OpenFolder(string path)
    {
        Directory.CreateDirectory(path);
        Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    }

    private static void WriteFlag(string name)
    {
        try
        {
            var production = Path.Combine(dataDir, "production");
            Directory.CreateDirectory(production);
            var seconds = (DateTime.UtcNow - Epoch).TotalSeconds;
            File.WriteAllText(Path.Combine(production, name), seconds.ToString("R", System.Globalization.CultureInfo.InvariantCulture));
        }
        catch { }
    }

    // Das Dashboard haelt dashboard.lock (Python, Bytesperre); ein Zugriff mit FileShare.None scheitert dann.
    private static bool DashboardRunning()
    {
        try
        {
            using (new FileStream(Path.Combine(dataDir, "production", "dashboard.lock"), FileMode.Open, FileAccess.ReadWrite, FileShare.None)) { }
            return false;
        }
        catch (FileNotFoundException) { return false; }
        catch (DirectoryNotFoundException) { return false; }
        catch (IOException) { return true; }
    }

    private static void OpenDashboard()
    {
        if (DashboardRunning())
        {
            WriteFlag("dashboard-show.flag"); // schon offen: nur nach vorn holen
            return;
        }
        if (Python() != null && File.Exists(Path.Combine(appDir, "vodwerft", "NightcutDashboard.pyw")))
        {
            StartScript("NightcutDashboard.pyw");
            return;
        }
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        var shortcut = Path.Combine(desktop, Product + ".lnk");
        try
        {
            Process.Start(new ProcessStartInfo(shortcut) { UseShellExecute = true });
        }
        catch (System.ComponentModel.Win32Exception)
        {
            MessageBox.Show("Die Verknüpfung „" + Product + "“ fehlt auf dem Desktop.",
                            Product, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private static Dictionary<string, object> ReadStatus(JavaScriptSerializer json, string path)
    {
        try
        {
            string snapshot;
            using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new StreamReader(file)) snapshot = reader.ReadToEnd();
            var data = json.Deserialize<Dictionary<string, object>>(snapshot);
            object updated;
            if (data != null && data.TryGetValue("updated", out updated)
                && (DateTime.UtcNow - Epoch).TotalSeconds - Convert.ToInt64(updated) < 45) return data;
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        catch (ArgumentException) { }
        catch (InvalidOperationException) { }
        return new Dictionary<string, object>();
    }
}
