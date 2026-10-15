using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using AudionImageTools.Core;
using Page = AudionImageTools.Core.Page;

namespace AudionImageTools;

/// <summary>
/// The preview: in the lower left corner, under the form (the owner, 14.10.2026), what the operation of
/// the page makes of one picture of the Source before it is run on all - cutting, cropping, turning, a
/// size, a watermark. The window draws nothing of its own: the console command runs the same command
/// line of the engine on a copy of the picture made smaller (system_core\cli.py, preview) and hands back
/// the copy and what was made of it. The form is seen again a moment after a field stops changing; an
/// answer that comes after a newer question is dropped. The layout says which pages show it
/// (config\window_layout.yaml, preview: true).
///
/// The frame holds two pictures of 16:9 side by side - "before" and "after" - and one picture fitted
/// into it alone (the owner, 14.10.2026: "smaller, so that two 16:9 fit; if it fits with the controls,
/// so"). Every control of the preview - the name of the picture, the steps through the Source, before
/// and after, again, fold - and the facts stand at the right of the frame when the width allows, and
/// over it when it does not.
/// </summary>
public partial class MainWindow
{
    /// <summary>The width of the frame of two 16:9: never less, never more, whatever the room.</summary>
    const double FrameLeast = 380, FrameMost = 680;
    /// <summary>The width the controls and the facts take at the right of the frame.</summary>
    const double SideWidth = 290;
    /// <summary>The least height left to the form over the preview.</summary>
    const double FormLeast = 170;

    static readonly HashSet<string> PreviewSuffixes = new(StringComparer.OrdinalIgnoreCase)
    { ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif", ".heic", ".heif", ".avif", ".cr2", ".cr3", ".dng" };

    readonly DispatcherTimer _previewSoon = new() { Interval = TimeSpan.FromMilliseconds(450) };
    int _previewAt, _previewAsked;
    string _previewMode = "after";
    bool _previewFolded;
    double _frameWidth = FrameMost;
    bool _sideBeside = true;
    StackPanel _pvSide = null!;
    Bitmap? _previewBefore, _previewAfter;
    Values? _previewValues;
    TextBlock _pvName = null!, _pvCount = null!, _pvFacts = null!, _pvState = null!;
    Grid _pvPictures = null!;
    Border _pvFrame = null!;
    readonly List<ToggleButton> _pvModes = new();
    Button _pvFold = null!;

    void WirePreview()
    {
        Button Tool(string icon, string tip, string id, Action act)
        {
            var button = new Button { Classes = { "tool" }, Content = Icons.Sign(icon), VerticalAlignment = VerticalAlignment.Center };
            ToolTip.SetTip(button, Lang.T(tip));
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, id);
            button.Click += (_, _) => act();
            return button;
        }

        // The frame of the picture, at the left: the pictures fitted into it, a chequer under each.
        _pvPictures = new Grid();
        _pvFrame = new Border { Classes = { "listbg" }, CornerRadius = new CornerRadius(5), Padding = new Thickness(6), ClipToBounds = true, Child = _pvPictures, VerticalAlignment = VerticalAlignment.Top };

        // At its right, every control of the preview, the facts under them.
        var side = _pvSide = new StackPanel { Margin = new Thickness(12, 0, 0, 0), Spacing = 6 };
        var title = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        title.Children.Add(new TextBlock { Classes = { "cardtitle" }, Text = Lang.T("ПРЕДПРОСМОТР"), VerticalAlignment = VerticalAlignment.Center });
        _pvFold = Tool("minimize-2", "Свернуть предпросмотр: форме - всё место", "preview_fold", () => { _previewFolded = !_previewFolded; FoldPreview(); });
        title.Children.Add(Tool("refresh-cw", "Посчитать снова", "preview_again", () => { _ = RefreshPreview(); }));
        title.Children.Add(_pvFold);
        side.Children.Add(title);
        _pvName = new TextBlock { Classes = { "note" }, TextTrimming = TextTrimming.CharacterEllipsis };
        side.Children.Add(_pvName);
        var tools = new WrapPanel { Orientation = Orientation.Horizontal };
        var steps = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4, Margin = new Thickness(0, 0, 10, 4) };
        steps.Children.Add(Tool("chevron-left", "Предыдущая картинка источника", "preview_back", () => StepPreview(-1)));
        _pvCount = new TextBlock { Classes = { "note" }, VerticalAlignment = VerticalAlignment.Center, MinWidth = 44, TextAlignment = TextAlignment.Center };
        steps.Children.Add(_pvCount);
        steps.Children.Add(Tool("chevron-right", "Следующая картинка источника", "preview_next", () => StepPreview(+1)));
        tools.Children.Add(steps);
        var modes = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 0, 6, 4) };
        foreach (var (key, word) in new[] { ("before", "До"), ("after", "После"), ("both", "Рядом") })
        {
            var mode = new ToggleButton { Classes = { "switch" }, Content = Lang.T(word), Tag = key, Margin = new Thickness(0, 0, 4, 0), IsChecked = key == _previewMode };
            Avalonia.Automation.AutomationProperties.SetAutomationId(mode, "preview_" + key);
            mode.Click += (_, _) => { _previewMode = key; foreach (var one in _pvModes) one.IsChecked = (string?)one.Tag == key; ShowPictures(); };
            _pvModes.Add(mode);
            modes.Children.Add(mode);
        }
        tools.Children.Add(modes);
        side.Children.Add(tools);
        _pvFacts = new TextBlock { Classes = { "note" }, TextWrapping = TextWrapping.Wrap };
        _pvState = new TextBlock { Classes = { "note" }, TextWrapping = TextWrapping.Wrap };
        Avalonia.Automation.AutomationProperties.SetAutomationId(_pvState, "preview_state");
        side.Children.Add(_pvFacts);
        side.Children.Add(_pvState);

        var band = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), RowDefinitions = new RowDefinitions("Auto,Auto") };
        band.Children.Add(_pvFrame);
        Grid.SetColumn(side, 1);
        band.Children.Add(side);
        PreviewCard.Child = band;

        _previewSoon.Tick += (_, _) => { _previewSoon.Stop(); _ = RefreshPreview(); };
        WorkArea.LayoutUpdated += (_, _) => FitPreview();
    }

    /// <summary>A page comes into sight: the preview is shown when the layout gives it one, and listens to its fields.</summary>
    void ShowPreview(Page page)
    {
        bool on = page.Preview && Door.Ready;
        PreviewCard.IsVisible = on;
        if (_previewValues is not null) _previewValues.Changed -= PreviewHeard;
        _previewValues = on ? _store.Of(page) : null;
        if (_previewValues is not null) _previewValues.Changed += PreviewHeard;
        if (!on) return;
        _previewAt = 0;
        PreviewSoon();
    }

    void PreviewHeard(string _) => PreviewSoon();

    /// <summary>The preview is asked again a moment after the last change: a slider dragged asks once.</summary>
    void PreviewSoon()
    {
        if (!PreviewCard.IsVisible || _previewFolded) return;
        _previewSoon.Stop();
        _previewSoon.Start();
    }

    void StepPreview(int by)
    {
        _previewAt += by;
        _ = RefreshPreview();
    }

    void FoldPreview()
    {
        _pvFrame.IsVisible = !_previewFolded;
        _pvFacts.IsVisible = _pvState.IsVisible = !_previewFolded;
        _pvFold.Content = Icons.Sign(_previewFolded ? "maximize-2" : "minimize-2");
        ToolTip.SetTip(_pvFold, Lang.T(_previewFolded ? "Развернуть предпросмотр" : "Свернуть предпросмотр: форме - всё место"));
        if (!_previewFolded) PreviewSoon();
    }

    /// <summary>
    /// The frame as wide as the card allows beside the controls - between its least and its most - and as
    /// high as two 16:9 of that width; lower when the room under the form is less. The controls go over the
    /// frame when the card is too narrow for both side by side.
    /// </summary>
    void FitPreview()
    {
        if (!PreviewCard.IsVisible || _previewFolded || _view is null) return;
        double area = WorkArea.Bounds.Height, card = PreviewCard.Bounds.Width - PreviewCard.Padding.Left - PreviewCard.Padding.Right;
        if (area <= 0 || card <= 0) return;
        double rim = _pvFrame.Padding.Left + _pvFrame.Padding.Right;
        bool beside = card - SideWidth - 12 - rim >= FrameLeast;
        double width = beside ? Math.Clamp(card - SideWidth - 12 - rim, FrameLeast, FrameMost) : Math.Min(card - rim, FrameMost);
        // The room under the form: the frame grows no higher than it, down to the least width.
        double form = _view.Cards.DesiredSize.Height + _view.Cards.Margin.Top + _view.Cards.Margin.Bottom + 6;
        double chrome = PreviewCard.Padding.Top + PreviewCard.Padding.Bottom + PreviewCard.Margin.Bottom + _pvFrame.Padding.Top + _pvFrame.Padding.Bottom + 2
                        + (beside ? 0 : _pvSide.DesiredSize.Height + 6);
        double room = Math.Min(area - form, area - FormLeast) - chrome;
        if (HeightOf(width) > room) width = Math.Max(FrameLeast, Math.Min(width, WidthOf(room)));
        if (Math.Abs(width - _frameWidth) > 2 || beside != _sideBeside)
        {
            _frameWidth = width;
            _sideBeside = beside;
            Grid.SetColumnSpan(_pvSide, beside ? 1 : 2);
            Grid.SetColumn(_pvSide, beside ? 1 : 0);
            Grid.SetRow(_pvFrame, beside ? 0 : 1);
            _pvSide.Margin = beside ? new Thickness(12, 0, 0, 0) : new Thickness(0, 0, 0, 6);
            SizeFrame();
        }
    }

    /// <summary>The rule between "before" and "after", with its air at both sides.</summary>
    const double Between = 13;

    /// <summary>Two 16:9 side by side with the rule between them: their height for a width, and the width for a height.</summary>
    static double HeightOf(double width) => (width - Between) / 2 * 9 / 16;

    static double WidthOf(double height) => height * 16 / 9 * 2 + Between;

    void SizeFrame()
    {
        _pvPictures.Width = _frameWidth;
        _pvPictures.Height = HeightOf(_frameWidth);
    }

    /// <summary>The pictures of the Source the preview may show: a file, or the pictures of a folder and its folders, in the order of their names.</summary>
    List<string> PreviewPictures()
    {
        try
        {
            if (File.Exists(_source)) return PreviewSuffixes.Contains(Path.GetExtension(_source)) ? new List<string> { _source } : new List<string>();
            if (!Directory.Exists(_source)) return new List<string>();
            return Directory.EnumerateFiles(_source, "*", SearchOption.AllDirectories)
                .Where(path => PreviewSuffixes.Contains(Path.GetExtension(path)))
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase).Take(1000).ToList();
        }
        catch { return new List<string>(); }
    }

    async Task RefreshPreview()
    {
        if (_page is not { Preview: true } page || !PreviewCard.IsVisible || _previewFolded) return;
        var node = page.Operations.FirstOrDefault(one => one.Runs && one.Beside.Length == 0);
        if (node is null) return;
        var pictures = PreviewPictures();
        if (pictures.Count == 0)
        {
            _pvName.Text = "";
            _pvCount.Text = "0 / 0";
            _previewBefore = _previewAfter = null;
            _pvFacts.Text = "";
            Say(Lang.T("В источнике нет картинок: предпросмотру нечего показать."), "");
            ShowPictures();
            return;
        }
        _previewAt = ((_previewAt % pictures.Count) + pictures.Count) % pictures.Count;
        var file = pictures[_previewAt];
        _pvName.Text = Path.GetFileName(file);
        ToolTip.SetTip(_pvName, Paths.Short(file));
        _pvCount.Text = $"{_previewAt + 1} / {pictures.Count}";
        int asked = ++_previewAsked;
        Say(Lang.T("Считаю…"), "");
        var folder = Path.Combine(Paths.Session, "preview", asked.ToString());
        var values = Path.Combine(Paths.Session, "preview", $"params-{asked}.json");
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(values)!);
            await File.WriteAllTextAsync(values, _store.Of(page).ForDoor(node), new UTF8Encoding(false));
        }
        catch (Exception ex) { Say(Lang.F("предпросмотр не подготовлен: {0}", ex.Message), "bad"); return; }
        var reply = await Door.Call(new[] { "preview", "--operation", node.Id, "--file", file, "--out", folder, "--params", values }, 90_000);
        try { File.Delete(values); } catch { }
        if (asked != _previewAsked) { Forget(folder); return; }
        var line = reply.Out.Split('\n').Select(text => text.Trim()).LastOrDefault(text => text.StartsWith(Door.Control + "{\"preview\"", StringComparison.Ordinal));
        if (line is null)
        {
            Say(Lang.F("предпросмотр не получен: {0}", FirstWords(reply.Err.Length > 0 ? reply.Err : reply.Out)), "bad");
            return;
        }
        try
        {
            using var doc = JsonDocument.Parse(line[Door.Control.Length..]);
            var told = doc.RootElement.GetProperty("preview");
            if (told.TryGetProperty("error", out var error))
            {
                Say(Lang.F("предпросмотр не получен: {0}", error.GetString() ?? ""), "bad");
                _previewAfter = null;
                ShowPictures();
                return;
            }
            _previewBefore = Load(told.GetProperty("before").GetString() ?? "");
            var after = told.GetProperty("after");
            var first = after.GetArrayLength() > 0 ? after[0] : default;
            _previewAfter = first.ValueKind == JsonValueKind.Object ? Load(first.GetProperty("path").GetString() ?? "") : null;
            _pvFacts.Text = Facts(told, first, after.GetArrayLength() > 0 ? told.GetProperty("made").GetInt32() : 0);
            var copy = _previewBefore is { } shown ? Math.Max(shown.PixelSize.Width, shown.PixelSize.Height) : 0;
            var culture = System.Globalization.CultureInfo.GetCultureInfo(Lang.Code == "ru" ? "ru-RU" : "en-US");
            Say(Lang.F("Посчитано за {0} с на копии {1} px.", told.GetProperty("seconds").GetDouble().ToString("0.0", culture), copy), "good");
            ShowPictures();
        }
        catch (Exception ex) { Say(Lang.F("предпросмотр не прочитан: {0}", ex.Message), "bad"); }
        finally { Forget(folder); }
    }

    /// <summary>The folder of an answer: thrown away once its pictures are in memory, or once a newer question is asked.</summary>
    static void Forget(string folder)
    {
        try { if (Directory.Exists(folder)) Directory.Delete(folder, true); } catch { }
    }

    /// <summary>A picture read into memory: its file may go at once.</summary>
    static Bitmap? Load(string path)
    {
        try
        {
            if (path.Length == 0 || !File.Exists(path)) return null;
            using var stream = new MemoryStream(File.ReadAllBytes(path));
            return new Bitmap(stream);
        }
        catch { return null; }
    }

    static string FirstWords(string text) => text.Split('\n').Select(line => line.Trim()).LastOrDefault(line => line.Length > 0) ?? "";

    void Say(string text, string tone)
    {
        _pvState.Text = text;
        _pvState.Classes.Set("bad", tone == "bad");
        _pvState.Classes.Set("good", tone == "good");
    }

    /// <summary>The facts under the controls: the source - its pixels, its density, its millimetres; what is made of it at full size.</summary>
    static string Facts(JsonElement told, JsonElement first, int made)
    {
        var lines = new List<string>();
        var pixels = told.GetProperty("pixels");
        int width = pixels[0].GetInt32(), height = pixels[1].GetInt32();
        var line = Lang.T("Исходник") + ": " + $"{width} × {height} px";
        if (told.TryGetProperty("dpi", out var dpi) && dpi.ValueKind == JsonValueKind.Array)
        {
            double x = dpi[0].GetDouble(), y = dpi[1].GetDouble();
            line += $" · {Math.Round(x)} dpi · {width / x * 25.4:0.#} × {height / y * 25.4:0.#} " + Lang.T("мм");
        }
        lines.Add(line);
        if (first.ValueKind == JsonValueKind.Object)
        {
            var full = first.GetProperty("full_pixels");
            lines.Add(Lang.T("Результат") + ": " + $"{full[0].GetInt32()} × {full[1].GetInt32()} px");
            if (made > 1) lines.Add(Lang.F("файлов из одной картинки: {0}", made));
        }
        return string.Join("\n", lines);
    }

    /// <summary>The pictures as the mode asks: before, after, or both side by side - each fitted into its cell on a chequer that shows what is transparent.</summary>
    void ShowPictures()
    {
        SizeFrame();
        _pvPictures.Children.Clear();
        _pvPictures.ColumnDefinitions.Clear();
        var shown = _previewMode switch
        {
            "before" => new[] { (_previewBefore, "") },
            "both" => new[] { (_previewBefore, Lang.T("До")), (_previewAfter, Lang.T("После")) },
            _ => new[] { (_previewAfter ?? _previewBefore, "") },
        };
        for (int at = 0; at < shown.Length; at++)
        {
            if (at > 0)
            {
                // A rule between "before" and "after" (the owner, 14.10.2026).
                _pvPictures.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
                var rule = new Border { Width = 1, Margin = new Thickness((Between - 1) / 2, 0), VerticalAlignment = VerticalAlignment.Stretch };
                rule.Bind(Border.BackgroundProperty, rule.GetResourceObservable("BorderSoft"));
                Grid.SetColumn(rule, _pvPictures.ColumnDefinitions.Count - 1);
                _pvPictures.Children.Add(rule);
            }
            _pvPictures.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            var (picture, caption) = shown[at];
            var cell = new Grid { RowDefinitions = new RowDefinitions("Auto,*") };
            // The caption stands over the middle of its picture.
            if (caption.Length > 0) cell.Children.Add(new TextBlock { Classes = { "factname" }, Text = caption, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 0, 0, 3) });
            if (picture is not null)
            {
                var frame = new Border
                {
                    Background = Chequer, BorderThickness = new Thickness(1),
                    HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
                    Child = new Image { Source = picture, Stretch = Stretch.Uniform },
                };
                // The rim of the theme in sight, followed when the theme changes.
                frame.Bind(Border.BorderBrushProperty, frame.GetResourceObservable("BorderSoft"));
                Grid.SetRow(frame, 1);
                cell.Children.Add(frame);
            }
            Grid.SetColumn(cell, _pvPictures.ColumnDefinitions.Count - 1);
            _pvPictures.Children.Add(cell);
        }
    }

    static IBrush? _chequer;

    /// <summary>Squares of two greys under a picture: its transparent parts show as such.</summary>
    static IBrush Chequer => _chequer ??= new DrawingBrush(new DrawingGroup
    {
        Children =
        {
            new GeometryDrawing { Brush = new SolidColorBrush(Color.Parse("#3a3a3a")), Geometry = new RectangleGeometry(new Rect(0, 0, 16, 16)) },
            new GeometryDrawing { Brush = new SolidColorBrush(Color.Parse("#4a4a4a")), Geometry = new RectangleGeometry(new Rect(0, 0, 8, 8)) },
            new GeometryDrawing { Brush = new SolidColorBrush(Color.Parse("#4a4a4a")), Geometry = new RectangleGeometry(new Rect(8, 8, 8, 8)) },
        },
    })
    {
        TileMode = TileMode.Tile, Stretch = Stretch.None,
        DestinationRect = new RelativeRect(0, 0, 16, 16, RelativeUnit.Absolute),
    };
}
