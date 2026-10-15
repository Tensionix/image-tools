using System.Collections.Generic;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;

namespace AudionImageTools.Views;

/// <summary>
/// The colour a choice of a form wears, as the window on NiceGUI had it: a way of resampling in
/// cyan, a lossy format in amber, "as it is" in green, a choice that opens a number of its own in
/// red. Which tone a choice has is told by the console command (operation_model.option_tone) - the
/// window does not guess it from the words of the choice. What a tone looks like is here: the
/// pairs of colours are resources of the shell (App.axaml, Tone...), and a switch wears them as
/// brushes of its own under the keys its style reads.
///
/// At rest the rim of a toned switch is quiet - a fifth of its colour - and the wash carries the
/// tone; the chosen one has the bright rim and a deeper wash.
/// </summary>
public static class ChoiceTones
{
    /// <summary>The tone of a choice - the pair of colours it is drawn with.</summary>
    static readonly Dictionary<string, string> Pairs = new()
    {
        ["process"] = "Process", ["graphics"] = "Process", ["lossless"] = "Process",
        ["photo"] = "Photo", ["lossy"] = "Photo",
        ["raw"] = "Raw", ["source"] = "Raw",
        ["warn"] = "Warn",
        ["dpi"] = "Dpi", ["local"] = "Dpi",
        ["model"] = "Model", ["vision"] = "Model", ["documents"] = "Model",
    };

    /// <summary>
    /// Tones that are the colour they name - grey, sepia, a tint (the owner, 14.10.2026: "draw them in their soft
    /// colour" in place of words): one soft colour in every theme, a little more of it at rest than a pair of the theme.
    /// </summary>
    static readonly Dictionary<string, string> Own = new() { ["gray"] = "#a3a3a3", ["sepia"] = "#b38b5d", ["tint"] = "#5f93c9" };

    /// <summary>How much of the tone goes into the rim at rest, the wash at rest, the chosen wash and the chosen rim.</summary>
    public const double RimAtRest = 0.20, WashAtRest = 0.07, WashOn = 0.30, RimOn = 0.78;

    static readonly Dictionary<string, Dictionary<string, IBrush>> Made = new();
    static object? _madeFor;

    static Color Mix(Color a, double share, Color b) => Color.FromRgb(
        (byte)(a.R * share + b.R * (1 - share)), (byte)(a.G * share + b.G * (1 - share)), (byte)(a.B * share + b.B * (1 - share)));

    static bool Colour(string key, out Color colour)
    {
        colour = default;
        if (Application.Current is not { } app || !app.TryGetResource(key, app.ActualThemeVariant, out var value)) return false;
        if (value is Color plain) { colour = plain; return true; }
        if (value is ISolidColorBrush brush) { colour = brush.Color; return true; }
        return false;
    }

    /// <summary>True when the tone is one the window draws.</summary>
    public static bool Known(string tone) => Pairs.ContainsKey(tone) || Own.ContainsKey(tone);

    /// <summary>
    /// A switch puts on its tone: the brushes go into its own resources under the keys the style
    /// of a switch reads, so the style needs no copy for every tone. A choice without a tone, or
    /// with one the window does not know, stays as the shell draws it.
    /// </summary>
    public static void Wear(Control button, string tone)
    {
        bool own = Own.TryGetValue(tone, out var hex);
        if (!own && !Pairs.TryGetValue(tone, out _)) return;
        var pair = own ? tone : Pairs[tone];
        var theme = Application.Current?.ActualThemeVariant;
        if (!ReferenceEquals(theme, _madeFor)) { Made.Clear(); _madeFor = theme; }
        if (!Made.TryGetValue(pair, out var brushes) && own)
        {
            if (!Colour("PanelBg", out var ground)) return;
            var soft = Color.Parse(hex!);
            Made[pair] = brushes = new Dictionary<string, IBrush>
            {
                ["SwitchBg"] = new SolidColorBrush(Mix(soft, 0.16, ground)),
                ["SwitchBorder"] = new SolidColorBrush(Mix(soft, 0.34, ground)),
                ["SwitchOn"] = new SolidColorBrush(Mix(soft, 0.38, ground)),
                ["Quasar"] = new SolidColorBrush(Mix(soft, 0.85, ground)),
            };
        }
        if (brushes is null)
        {
            if (!Colour("Tone" + pair, out var accent) || !Colour("Tone" + pair + "Bright", out var bright) || !Colour("PanelBg", out var ground)) return;
            Made[pair] = brushes = new Dictionary<string, IBrush>
            {
                ["SwitchBg"] = new SolidColorBrush(Mix(accent, WashAtRest, ground)),
                ["SwitchBorder"] = new SolidColorBrush(Mix(accent, RimAtRest, ground)),
                ["SwitchOn"] = new SolidColorBrush(Mix(accent, WashOn, ground)),
                ["Quasar"] = new SolidColorBrush(Mix(bright, RimOn, ground)),
            };
        }
        foreach (var (key, brush) in brushes) button.Resources[key] = brush;
    }
}
