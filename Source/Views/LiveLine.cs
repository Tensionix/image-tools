using System.Text.RegularExpressions;
using Avalonia.Controls;
using Avalonia.Controls.Documents;

namespace AudionImageTools.Views;

/// <summary>
/// The live line of the terminal in its colours:
///
///     Processing: 42% · 5 / 12 · 9.28 file/s · scan 07.jpg
///
/// how much is there - green, how much there will be - orange, the speed - blue, what parts them -
/// quiet, the rest as a line of the terminal. The line is the operation's own (system_core\cli.py
/// makes it of the bar the engine draws and of the files of a batch it folds); the window reads
/// counts, sizes and a speed in it wherever they stand and knows no operation by its words. Until
/// 3.0.0 the pattern took a count only with bytes ("132.0 / 148.9 MB", the download of Get Tools):
/// "5 / 12" and "file/s" stood uncoloured.
/// </summary>
public static class LiveLine
{
    static readonly Regex Parts = new(
        @"(?<![\w.,])(?<done>\d+(?:[.,]\d+)?(?:\s*[KMGT]?i?B)?)(?<slash>\s*/\s*)(?<total>\d+(?:[.,]\d+)?(?:\s*[KMGT]?i?B)?)(?![\w/.,])" +
        @"|(?<![\w.,])(?<speed>\d+(?:[.,]\d+)?\s*[A-Za-z]+/s)(?!\w)" +
        @"|(?<![\w.,])(?<percent>\d{1,3}(?:[.,]\d+)?%)" +
        @"|(?<eta>ETA)(?<gap>\s+)(?<left>\d+(?::\d\d){1,2})(?![\d:])" +
        @"|(?<![\w.,])(?<size>\d+(?:[.,]\d+)?\s*[KMGT]?i?B)(?![\w/])" +
        @"|(?<dot> · )",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    // "Processing:" - what the line is of: quiet, the measures after it are what is read.
    static readonly Regex Label = new(@"^[^:·]{1,40}:\s", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>
    /// Every measure in a tone of its own (the owner, 14.10.2026: "the count, the ETA and the rest -
    /// in different accents"): the share done, how much is there, how much there will be, the speed,
    /// the time left; the name of the file in the colour of the text, the label quiet.
    /// </summary>
    public static void Paint(TextBlock block, string text)
    {
        var inlines = block.Inlines ??= new InlineCollection();
        inlines.Clear();
        void Add(string piece, string key)
        {
            if (piece.Length > 0) inlines.Add(new Run(piece) { Foreground = App.Ink(key) });
        }
        int at = 0;
        if (Label.Match(text) is { Success: true } label)
        {
            Add(label.Value, "LogMuted");
            at = label.Length;
        }
        foreach (Match match in Parts.Matches(text, at))
        {
            Add(text[at..match.Index], "LogPlain");
            if (match.Groups["total"].Success)
            {
                Add(match.Groups["done"].Value, "LiveDone");
                Add(match.Groups["slash"].Value, "LogMuted");
                Add(match.Groups["total"].Value, "LiveTotal");
            }
            else if (match.Groups["speed"].Success) Add(match.Value, "LiveSpeed");
            else if (match.Groups["percent"].Success) Add(match.Value, "LivePercent");
            else if (match.Groups["left"].Success)
            {
                Add(match.Groups["eta"].Value + match.Groups["gap"].Value, "LogMuted");
                Add(match.Groups["left"].Value, "LiveEta");
            }
            else if (match.Groups["size"].Success) Add(match.Value, "LiveDone");
            else Add(match.Value, "LogMuted");
            at = match.Index + match.Length;
        }
        Add(text[at..], "LogPlain");
    }

    /// <summary>The line while the operation has nothing to say of itself: its name, quiet.</summary>
    public static void Quiet(TextBlock block, string text)
    {
        var inlines = block.Inlines ??= new InlineCollection();
        inlines.Clear();
        inlines.Add(new Run(text) { Foreground = App.Ink("LogMuted") });
    }
}
