using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Avalonia.Input;
using AudionImageTools.Core;

namespace AudionImageTools;

/// <summary>
/// THREADS in the header: how many files the engine works on at once - a number, and the two
/// arrows that step it (the owner, 14.10.2026: "a field with a spinner, and so we write: THREADS;
/// in the row of the themes and the language, left of FORMATS"). One setting of the window for
/// every operation that can share its work. It is kept where the engine has always read it -
/// config\parallel_settings.json, read by the service at every start of an operation
/// (system_core\services\image_tools_gui.py): 1 is "one by one" and is written as the threads
/// switched off, with the number last chosen kept beside it.
/// </summary>
public partial class MainWindow
{
    const int MostThreads = 24, UsualThreads = 8;
    int _threads = 1;

    // A check keeps its own number beside its build: the setting of the owner is not a check's to change.
    static string ThreadsFile => Paths.Released ? Path.Combine(Paths.Config, "parallel_settings.json") : Path.Combine(Paths.Runtime, "parallel_settings.json");

    void WireThreads()
    {
        _threads = ReadThreads().InUse;
        ThreadsBox.Text = _threads.ToString(CultureInfo.InvariantCulture);
        ThreadsUp.Click += (_, _) => SetThreads(_threads + 1);
        ThreadsDown.Click += (_, _) => SetThreads(_threads - 1);
        ThreadsBox.LostFocus += (_, _) => TakeThreads();
        ThreadsBox.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { TakeThreads(); Shell.Focus(); e.Handled = true; }
            else if (e.Key == Key.Up) { TakeThreads(); SetThreads(_threads + 1); e.Handled = true; }
            else if (e.Key == Key.Down) { TakeThreads(); SetThreads(_threads - 1); e.Handled = true; }
        };
    }

    /// <summary>What was typed into the box: a number is taken and kept inside 1-24, anything else goes back to what stood there.</summary>
    void TakeThreads()
    {
        if (int.TryParse((ThreadsBox.Text ?? "").Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var typed)) SetThreads(typed);
        else ThreadsBox.Text = _threads.ToString(CultureInfo.InvariantCulture);
    }

    void SetThreads(int threads)
    {
        threads = Math.Clamp(threads, 1, MostThreads);
        ThreadsBox.Text = threads.ToString(CultureInfo.InvariantCulture);
        if (threads == _threads) return;
        _threads = threads;
        WriteThreads(threads);
    }

    /// <summary>What the file says: the threads in use (1 - switched off) and the number kept for when they are on.</summary>
    static (int InUse, int Kept) ReadThreads()
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(ThreadsFile));
            var root = doc.RootElement;
            bool on = root.TryGetProperty("parallel_enabled", out var enabled) && enabled.ValueKind == JsonValueKind.True;
            int kept = root.TryGetProperty("worker_count", out var count) && count.TryGetInt32(out var number) ? Math.Clamp(number, 1, MostThreads) : UsualThreads;
            return (on ? kept : 1, kept);
        }
        catch { return (1, UsualThreads); }
    }

    /// <summary>The file written whole or not at all; a file that could not be written is said in the status line.</summary>
    void WriteThreads(int threads)
    {
        try
        {
            var payload = new JsonObject
            {
                ["parallel_enabled"] = threads > 1,
                ["worker_count"] = threads > 1 ? threads : ReadThreads().Kept,
            };
            Directory.CreateDirectory(Path.GetDirectoryName(ThreadsFile)!);
            var draft = ThreadsFile + ".tmp";
            File.WriteAllText(draft, payload.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", new UTF8Encoding(false));
            File.Move(draft, ThreadsFile, overwrite: true);
        }
        catch (Exception ex) { SetStatus(Lang.F("Число потоков не записано: {0}", ex.Message)); }
    }
}
