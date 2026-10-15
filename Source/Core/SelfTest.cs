using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading.Tasks;

namespace AudionImageTools.Core;

/// <summary>
/// What --self-test checks once the window has been put together: the parts of the window that
/// need no screen - what the door says of the program, the values of the fields, the line a run
/// is written with, the colours of the terminal. Each check answers with a line; one that failed
/// is named on the error stream, and the program ends with 2.
/// </summary>
public static class SelfTest
{
    /// <summary>
    /// Lines in the colours their writer gave them: a colour closed on its own line, the kinds of
    /// a colour and of a look, a colour left open and closed on the next line, a line nobody
    /// coloured. A picture of the terminal is taken with the same lines (MainWindow.Run.cs).
    /// </summary>
    public static readonly string[] ColouredLines =
    {
        "\u001b[33m[WARN] yellow by its writer\u001b[0m and plain after it",
        "\u001b[96mVivaldi\u001b[0m [\u001b[36mVivaldi.Vivaldi\u001b[0m] \u001b[1mbold\u001b[0m \u001b[2mdim\u001b[0m \u001b[4munderlined\u001b[0m \u001b[38;5;208mthe 208th\u001b[0m \u001b[38;2;120;200;80m24-bit\u001b[0m",
        "\u001b[31mred \u001b[32mgreen \u001b[34mblue \u001b[35mmagenta \u001b[90mgrey \u001b[97mwhite \u001b[93myellow",
        "still yellow: the colour was left open\u001b[0m",
        "[OK] a line nobody coloured",
    };

    sealed class Report
    {
        public readonly List<string> Passed = new();
        public readonly List<string> Failed = new();

        public void Check(string name, bool good, string found = "")
        {
            if (good) Passed.Add(name);
            else Failed.Add(found.Length > 0 ? name + ": " + found : name);
        }
    }

    /// <summary>A file the report is written to as well, "ok" and "FAIL" lines alike; "" - the two streams alone.</summary>
    public static string ReportFile { get; set; } = "";

    /// <summary>True when the build of App\ asks: the window was built a moment ago, and its number is checked too.</summary>
    public static bool JustBuilt { get; set; }

    /// <summary>Runs every check. What passed is written to the output, what failed to the error stream; true when nothing failed.</summary>
    public static bool Run()
    {
        var report = new Report();
        foreach (var check in new (string Name, Action<Report> Body)[]
        {
            ("version", Number),
            ("describe", Describe),
            ("forms", Forms),
            ("conditions", ConditionsOfFields),
            ("values sent", ValuesSent),
            ("run line", RunLine),
            ("source", SourceOfARun),
            ("colours", Colours),
            ("error stream", ErrorStream),
        })
        {
            try { check.Body(report); }
            catch (Exception error) { report.Failed.Add($"{check.Name}: {error.GetType().Name}: {error.Message}"); }
        }
        foreach (var line in report.Passed) try { Console.Out.WriteLine("ok   " + line); } catch { }
        foreach (var line in report.Failed) try { Console.Error.WriteLine("FAIL " + line); } catch { }
        if (ReportFile.Length > 0)
            try
            {
                System.IO.File.WriteAllLines(ReportFile, report.Passed.Select(line => "ok   " + line).Concat(report.Failed.Select(line => "FAIL " + line)), new System.Text.UTF8Encoding(false));
            }
            catch { }
        return report.Failed.Count == 0;
    }

    // ------------------------------------------------------------ what the console command tells of the program

    /// <summary>What the door said, for the checks that read the program itself.</summary>
    static Described? _told;

    static void Describe(Report report)
    {
        // Off the window's thread: nothing turns its queue here, and an answer awaited on it would never come.
        var (told, trouble) = Task.Run(Door.Describe).GetAwaiter().GetResult();
        report.Check("describe: the console command answered and the answer reads", told is not null, trouble);
        if (told is null) return;
        _told = told;
        var places = told.Operations().ToList();
        var nameless = places.Where(node => node.Id.Length == 0 || node.Title.Length == 0).Select(node => node.Id.Length > 0 ? node.Id : "(no id)").ToList();
        report.Check($"describe: each of the {places.Count} places of operations has a node and a name", places.Count > 0 && nameless.Count == 0, string.Join(", ", nameless));
        var homeless = told.Layout.Sections.SelectMany(section => section.Pages).SelectMany(page => page.Operations)
            .Where(node => node.Page?.Section is null).Select(node => node.Id).ToList();
        report.Check("describe: every operation of a page knows its page and its section", homeless.Count == 0, string.Join(", ", homeless));
        var pages = told.Layout.Sections.SelectMany(section => section.Pages).ToList();
        var formless = pages.Where(page => page.Operations.Count == 0 || page.Operations[0].Direct).Select(page => page.Id).ToList();
        report.Check($"describe: {told.Layout.Sections.Count} sections, {pages.Count} pages, each a form with its run", told.Layout.Sections.Count > 0 && formless.Count == 0,
            string.Join(", ", formless));
        var rows = pages.Where(page => page.Row is not ("images" or "documents")).Select(page => page.Id).ToList();
        report.Check("describe: every page stands in the row of pictures or of documents", rows.Count == 0, string.Join(", ", rows));
    }

    /// <summary>Every operation a page names: the run of its form and the quick ones beside it.</summary>
    static List<Node> Placed(Described told) =>
        told.Layout.Sections.SelectMany(section => section.Pages).SelectMany(page => page.Operations).ToList();

    /// <summary>
    /// Every form is built as the window builds it, and every field of it has its control: a field
    /// of a kind the window cannot draw would be an empty place, and is named here.
    /// </summary>
    static void Forms(Report report)
    {
        if (_told is not { } told) { report.Check("forms: the console command described the program", false, "no description"); return; }
        var store = new ValueStore(told.Layout.Shared);
        var unknown = new List<string>();
        int built = 0, fields = 0;
        foreach (var page in told.Layout.Sections.SelectMany(section => section.Pages))
        {
            var values = store.Open(page);
            foreach (var node in page.Operations.Where(node => node.Fields.Count > 0))
            {
                var form = new Views.Form(values, () => { });
                form.Build(node);
                unknown.AddRange(form.Unknown.Select(item => node.Id + "/" + item));
                built++;
                fields += node.Fields.Count;
            }
        }
        report.Check($"forms: {built} forms built, every one of their {fields} fields has its control", built > 0 && unknown.Count == 0, string.Join(", ", unknown));
    }

    static Node? Operation(string id) => _told is { } told ? Placed(told).FirstOrDefault(node => node.Id == id) : null;

    /// <summary>The conditions of the manifest as the window reads them: shown and hidden, switched on and off by another field.</summary>
    static void ConditionsOfFields(Report report)
    {
        if (Operation("downscale_percent") is not { } size || Operation("convert_images") is not { } convert)
        {
            report.Check("conditions: the operations they are checked on are described", false, "no downscale_percent or convert_images");
            return;
        }
        var values = new ValueStore().Of(size.Page);
        values.Learn(size.Fields);
        Field Of(Node node, string id) => node.Fields.First(field => field.Id == id);
        var percent = Of(size, "custom_percent");
        var quality = Of(size, "jpeg_quality");
        bool hidden = !Conditions.Visible(percent, values);
        values.Set(Of(size, "scale_mode"), "custom");
        bool shown = Conditions.Visible(percent, values);
        report.Check("conditions: \"own percent\" is out of sight at 50 % and in sight at \"custom\"", hidden && shown, $"at 50 %: {!hidden}, at custom: {shown}");
        values.Set(Of(size, "to"), "png");
        bool off = Conditions.Disabled(quality, values);
        values.Set(Of(size, "to"), "jpg");
        bool on = !Conditions.Disabled(quality, values);
        report.Check("conditions: \"quality\" is switched off for PNG and on for JPG", off && on, $"png off: {off}, jpg on: {on}");

        var ticks = new ValueStore().Of(convert.Page);
        ticks.Learn(convert.Fields);
        var formats = Of(convert, "to");
        var convertQuality = Of(convert, "jpeg_quality");
        ticks.Set(formats, "png" + Values.ListSeparator + "tiff");
        bool listOff = Conditions.Disabled(convertQuality, ticks);
        ticks.Set(formats, "png" + Values.ListSeparator + "webp");
        bool listOn = !Conditions.Disabled(convertQuality, ticks);
        report.Check("conditions: a list of formats switches \"quality\" off with PNG and TIFF alone, on with WebP among them", listOff && listOn, $"png+tiff off: {listOff}, png+webp on: {listOn}");
    }

    /// <summary>
    /// What the window would send the console command, operation by operation: the untouched form,
    /// and every choice of every switch set as its button sets it. Written beside the report
    /// (`report.txt.sent.json`) for tests\test_window_sends.py, which holds it to the rules of the
    /// command; here only that every value goes in the type the manifest wrote its option in.
    /// </summary>
    static void ValuesSent(Report report)
    {
        if (_told is not { } told) { report.Check("values sent: the console command described the program", false, "no description"); return; }
        var untouched = new System.Text.Json.Nodes.JsonObject();
        var choices = new System.Text.Json.Nodes.JsonArray();
        var mistyped = new List<string>();
        foreach (var page in told.Layout.Sections.SelectMany(section => section.Pages))
            foreach (var node in page.Operations.Where(node => node.Runs))
            {
                var store = new ValueStore();
                var values = store.Open(page);
                untouched[node.Id] = System.Text.Json.Nodes.JsonNode.Parse(values.ForDoor(node));
                foreach (var field in node.Fields.Where(field => field.Kind is "radio" or "select"))
                    foreach (var option in field.Options)
                    {
                        var fresh = new ValueStore().Open(page);
                        fresh.Set(field, option.Key);
                        var sent = System.Text.Json.Nodes.JsonNode.Parse(fresh.ForDoor(node))!;
                        var value = sent[field.Id];
                        if (value is null || value.GetValueKind() != option.Value.ValueKind) mistyped.Add($"{node.Id}/{field.Id}={option.Key}: {value?.ToJsonString()}");
                        choices.Add(new System.Text.Json.Nodes.JsonObject
                        {
                            ["operation"] = node.Id, ["field"] = field.Id, ["option"] = System.Text.Json.Nodes.JsonNode.Parse(option.Value.GetRawText()), ["sent"] = sent,
                        });
                    }
            }
        report.Check($"values sent: {untouched.Count} operations, {choices.Count} choices - every choice goes in the type of its option", untouched.Count > 0 && mistyped.Count == 0,
            string.Join("; ", mistyped.Take(6)));
        if (ReportFile.Length > 0)
            System.IO.File.WriteAllText(ReportFile + ".sent.json",
                new System.Text.Json.Nodes.JsonObject { ["untouched"] = untouched, ["choices"] = choices }.ToJsonString(new JsonSerializerOptions { WriteIndented = true }),
                new System.Text.UTF8Encoding(false));
    }

    /// <summary>Every page reads the Source the person chose: a run names it to the console command, and so does the line a person reads.</summary>
    static void SourceOfARun(Report report)
    {
        if (_told is not { } told) { report.Check("source: the console command described the program", false, "no description"); return; }
        var pages = told.Layout.Sections.SelectMany(section => section.Pages).ToList();
        report.Check("source: every page reads the Source", pages.Count > 0 && pages.All(page => page.Source), string.Join(", ", pages.Where(page => !page.Source).Select(ValueStore.KeyOf)));
        const string folder = @"D:\Chosen Source", target = @"E:\Results";
        static bool Names(IReadOnlyList<string> words, string key, string value) =>
            Enumerable.Range(0, words.Count - 1).Any(i => words[i] == key && words[i + 1] == value);
        var page = pages.First();
        var node = page.Operations.First(one => one.Runs);
        var source = Door.SourceOf(page, folder);
        var launch = Door.Run(node.Id, source, target);
        var line = Words(Door.RunLine(node.Id, source, target, new Dictionary<string, string>()));
        report.Check("source: a run names the Source and the Target to the console command, and in the line a person reads",
            Names(launch.Args, "--source", folder) && Names(launch.Args, "--target", target) && Names(line, "--source", folder) && launch.Args.Contains("--live"),
            string.Join(" ", launch.Args.Skip(5).Take(10)));
    }

    // ------------------------------------------------------------ the number of the program

    static void Number(Report report)
    {
        if (!JustBuilt) return;
        var built = typeof(SelfTest).Assembly.GetName().Version;
        var wanted = Paths.Version;
        var carried = built is null ? "" : $"{built.Major}.{built.Minor}.{built.Build}";
        report.Check("version: the executable carries the number of config\\version.json", wanted is not null && carried == wanted.Split('-', '+')[0], $"the executable {carried}, the file {wanted ?? "(unreadable)"}");
    }

    // ------------------------------------------------------------ what the door says of the program


    // ------------------------------------------------------------ the values of the fields

    // ------------------------------------------------------------ the line a run is written with

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CommandLineToArgvW(string line, out int count);

    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr memory);

    /// <summary>A line as Windows hands it to a program, word by word.</summary>
    static List<string> Words(string line)
    {
        var words = new List<string>();
        var raw = CommandLineToArgvW(line, out int count);
        if (raw == IntPtr.Zero) return words;
        try
        {
            for (int i = 0; i < count; i++) words.Add(Marshal.PtrToStringUni(Marshal.ReadIntPtr(raw, i * IntPtr.Size)) ?? "");
        }
        finally { LocalFree(raw); }
        return words;
    }

    static void RunLine(Report report)
    {
        // What a value may hold that a line has rules for: a space, a quote, a backslash at its end.
        var values = new Dictionary<string, string>
        {
            ["plain"] = "word",
            ["space"] = "two words",
            ["quote"] = "say \"yes\" twice",
            ["slash_end"] = @"C:\Some Folder\",
            ["slash_quote"] = "a\\\"b",
            ["slashes_end"] = @"name\\",
            ["empty"] = "",
            ["signs"] = "a&b|c<d>e^f",
        };
        var target = @"D:\Down Loads\";
        var source = @"E:\Some Source\";
        var line = Door.RunLine("downscale_percent", source, target, values);
        var expected = new List<string> { Paths.DoorName, "run", "--operation", "downscale_percent", "--source", Paths.Short(source), "--target", Paths.Short(target) };
        foreach (var (name, value) in values) { expected.Add("--set"); expected.Add(name + "=" + value); }
        var read = Words(line);
        var wrong = Enumerable.Range(0, Math.Max(expected.Count, read.Count))
            .Where(i => i >= expected.Count || i >= read.Count || expected[i] != read[i])
            .Select(i => $"word {i}: wanted <{(i < expected.Count ? expected[i] : "")}> read <{(i < read.Count ? read[i] : "")}>").ToList();
        report.Check("run line: read back word for word - a space, a quote, a backslash at the end of a value", wrong.Count == 0, string.Join("; ", wrong) + " | " + line);
    }

    // ------------------------------------------------------------ the lines of the error stream

    static void ErrorStream(Report report)
    {
        var read = new[] { "a plain word", "[ERR] named an error by its writer", "", "[ERROR] another word of the writer" }.Select(Runner.ErrorLine).ToArray();
        var expected = new[] { "[ERR] a plain word", "[ERR] named an error by its writer", "[ERR] ", "[ERR] [ERROR] another word of the writer" };
        report.Check("error stream: a line is marked [ERR] once", read.SequenceEqual(expected), string.Join(" ~ ", read));
    }

    // ------------------------------------------------------------ the colours of the terminal

    static void Colours(Report report)
    {
        static string Piece((string Text, Hue Hue) part) =>
            part.Text + "|" + (part.Hue.Own is { } own ? $"#{own.R:x2}{own.G:x2}{own.B:x2}" + (own.A < 255 ? "/" + own.A : "") : part.Hue.Key)
            + (part.Hue.Bold ? "|bold" : "") + (part.Hue.Underline ? "|underline" : "") + (part.Hue.Faint ? "|faint" : "");

        // The eight colours of every console in the tones of the theme; the 256 and the 24 bits as they are asked.
        var expected = new[]
        {
            new[] { "[WARN] yellow by its writer|LogWarn", " and plain after it|LogPlain" },
            new[]
            {
                "Vivaldi|LogHead", " [|LogPlain", "Vivaldi.Vivaldi|LogHead", "] |LogPlain", "bold|LogPlain|bold", " |LogPlain", "dim|LogMuted", " |LogPlain",
                "underlined|LogPlain|underline", " |LogPlain", "the 208th|#ff8700", " |LogPlain", "24-bit|#87d75f",
            },
            new[] { "red |LogBad", "green |LogGood", "blue |LiveSpeed", "magenta |#d946ef", "grey |LogMuted", "white |LogPlain", "yellow|LogWarn" },
            new[] { "still yellow: the colour was left open|LogWarn" },
            new[] { "[OK] a line nobody coloured|LogPlain" },
        };
        var plain = new[]
        {
            "[WARN] yellow by its writer and plain after it",
            "Vivaldi [Vivaldi.Vivaldi] bold dim underlined the 208th 24-bit",
            "red green blue magenta grey white yellow",
            "still yellow: the colour was left open",
            "[OK] a line nobody coloured",
        };
        var ansi = new Ansi();
        for (int i = 0; i < ColouredLines.Length; i++)
        {
            var parts = ansi.Read(ColouredLines[i], out var text).Select(Piece).ToArray();
            report.Check($"colours: line {i + 1} is read into its pieces", parts.SequenceEqual(expected[i]), string.Join(" ~ ", parts));
            report.Check($"colours: line {i + 1} as text alone", text == plain[i], text);
        }
        // A colour left open is over with the run: the next run starts plain.
        ansi.Read("\u001b[31mopen", out _);
        ansi.Reset();
        var after = ansi.Read("next run", out _).Select(Piece).ToArray();
        report.Check("colours: a colour left open does not outlive Reset", after.SequenceEqual(new[] { "next run|LogPlain" }), string.Join(" ~ ", after));
        // A dimmed colour is the same colour, fainter: one of the theme and one of its writer's own.
        var dim = new Ansi().Read("\u001b[2;31mfaint\u001b[0m \u001b[2;38;5;208mfainter\u001b[0m", out _).Select(Piece).ToArray();
        report.Check("colours: a dimmed colour keeps its tone", dim.SequenceEqual(new[] { "faint|LogBad|faint", " |LogPlain", "fainter|#ff8700/184" }), string.Join(" ~ ", dim));
    }
}
