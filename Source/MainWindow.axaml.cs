using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using AudionImageTools.Core;
using AudionImageTools.Views;
using Page = AudionImageTools.Core.Page;

namespace AudionImageTools;

/// <summary>
/// The window of Audion Image Tools. It installs and downloads nothing itself: every button runs an
/// operation of the manifest through the console door (image_cli.cmd) and shows what the operation
/// says. Which sections there are, what stands on their pages and which fields an operation has,
/// the door tells - the window knows none of them by name.
/// </summary>
public partial class MainWindow : Window
{
    readonly Settings _settings;
    readonly Runner _runner = new();
    /// <summary>The values of the fields: a store for every page, one of the window for the fields the layout names shared.</summary>
    ValueStore _store = new();
    Described? _told;
    Section? _section;
    Page? _page;
    /// <summary>The page each section was left at.</summary>
    readonly Dictionary<string, string> _lastPage = new();

    public MainWindow()
    {
        // The theme is the application's: set before the markup is read, so the window comes up in it.
        _settings = Settings.Load();
        Lang.Set(_settings.LanguageInUse);
        if (Application.Current is { } app) app.RequestedThemeVariant = App.Variant(_settings.Look);
        InitializeComponent();
        if (_settings.Width >= MinWidth && _settings.Height >= MinHeight)
        {
            Width = _settings.Width;
            Height = _settings.Height;
        }
        Classes.Set("vault", _settings.Look == "vault");
        App.SetFonts(_settings.UiFont, _settings.LogFont);
        App.SetSizes(_settings.UiShift, _settings.LogSize);
        // Words and signs on whole pixels of this screen, whatever its scale.
        PixelGrid.Apply(RenderScaling);
        ScalingChanged += (_, _) => PixelGrid.Apply(RenderScaling);

        var version = Paths.Version;
        Title = version is null ? "Audion Image Tools" : "Audion Image Tools v" + version;
        VersionText.Text = (version is null ? "version unknown" : "v" + version) + " • " + DateTime.Now.Year;

        _runner.Output += OnOutput;
        _runner.Finished += OnFinished;
        Guard.Told = message =>
        {
            AppendLines(new[] { "[GUI ERROR] " + message });
            SetStatus("Ошибка окна записана в logs.");
        };

        Wire();
        WireThreads();
        WireIo();
        WireResult();
        WirePreview();
        // The right part of the state row - the bar of a run, its clock and STOP - stands under the journal and is as
        // wide as it, whatever the splitter or the wide journal make of the column.
        RightZone.SizeChanged += (_, e) => StateRight.Width = Math.Max(0, e.NewSize.Width);
        // A pass of a check (-Shot of a Debug build) and a walk of the built window (AUDION_WALK=1) are
        // not for a person: the window stands off every screen, takes no focus and has no button on
        // the taskbar (the owner of Audion Get Tools: "I cannot make out by your millisecond switches
        // what belongs to what"). Its pictures are drawn from the window itself, not from a screen.
        bool offScreen = Program.Walk;
#if DEBUG
        // AUDION_SHOT_ON_SCREEN=1 puts a pass in sight.
        offScreen |= Program.ShotFolder.Length > 0 && Environment.GetEnvironmentVariable("AUDION_SHOT_ON_SCREEN") != "1";
#endif
        if (offScreen)
        {
            ShowInTaskbar = false;
            ShowActivated = false;
            WindowStartupLocation = WindowStartupLocation.Manual;
            Position = OffScreen;
        }
        MarkTheme();
        MarkLanguage();
        // What the markup holds is written in Russian: walked once, into the language in use.
        Lang.Walk(this);
        Closing += OnClosing;
        Opened += async (_, _) =>
        {
            // A place set before the window is shown is not kept: it came up at the corner of the
            // screen (measured 14.10.2026, -32000 and Manual alike). Set again once it is open.
            if (offScreen) Position = OffScreen;
            await StartUp();
#if DEBUG
            // AUDION_SHOT_HEIGHT: a pass may ask for a taller window - a long page in one picture. Off the screen it may be any height.
            if (Program.ShotFolder.Length > 0 && double.TryParse(Environment.GetEnvironmentVariable("AUDION_SHOT_HEIGHT"), out var tall) && tall > 400) Height = tall;
            if (Program.ShotFolder.Length > 0) await TakeShots(Program.ShotFolder);
#endif
        };
    }

    /// <summary>Where a window of a check stands: off every screen. Not -32000 - Windows reads that as "minimised".</summary>
    static readonly PixelPoint OffScreen = new(-30000, -30000);

    // ------------------------------------------------------------ the look

    void Wire()
    {
        LangRu.Click += (_, _) => SetLanguage("ru");
        LangEn.Click += (_, _) => SetLanguage("en");
        ThemeVault.Click += (_, _) => SetTheme("vault");
        ThemeDark.Click += (_, _) => SetTheme("dark");
        ThemeCode.Click += (_, _) => SetTheme("codedark");
        ThemeLight.Click += (_, _) => SetTheme("light");
        StopButton.Click += (_, _) => StopRun();
        CopyLogButton.Click += (_, _) => CopyLog();
        ClearLogButton.Click += (_, _) => ClearLog();
        WideLogButton.Click += (_, _) => ToggleWide();
        ActionReset.Click += (_, _) => { if (_view is { } view) ResetFields(view, view.ResetFields); };
        LogsButton.Click += (_, _) => OpenFolder(Paths.ProgramLogs);
        ReportButton.Click += (_, _) => OpenFolder(_told?.Paths.Report is { Length: > 0 } report ? report : Path.Combine(Paths.Root, "report"));
        ConfigButton.Click += (_, _) => OpenFolder(Paths.Config);
        _clock.Tick += (_, _) => ShowClock();
        SheetSettings.Click += (_, _) => ToggleSheet("settings");
        SheetAbout.Click += (_, _) => ToggleSheet("about");
        SheetClose.Click += (_, _) => ToggleSheet(_sheet);
        KeyDown += (_, e) =>
        {
            if (e.Key != Avalonia.Input.Key.Escape || _sheet.Length == 0) return;
            ToggleSheet(_sheet);
            e.Handled = true;
        };
    }

    void MarkLanguage()
    {
        LangRu.IsChecked = Lang.Code == "ru";
        LangEn.IsChecked = Lang.Code != "ru";
    }

    void SetLanguage(string code)
    {
        if (Lang.Code != code)
        {
            Lang.Set(code);
            _settings.Lang = code;
            _settings.Save();
            // What code wrote is written again in the new language; what the markup holds is walked.
            ForgetPages();
            BuildService();
            BuildSections();
            ShowAbilities();
            Lang.Walk(this);
            FillSheet();
        }
        MarkLanguage();
    }

    /// <summary>
    /// What the engine can do on this machine, badge by badge (system_core\core\abilities.py): HEIC, AVIF,
    /// RAW, Word, PowerPoint. A badge of what is missing wears the tone of a warning; the tooltip says
    /// what stands behind it, in the language of the window.
    /// </summary>
    void ShowAbilities()
    {
        MachineRow.Children.Clear();
        foreach (var ability in _told?.Abilities ?? new List<Ability>())
        {
            var badge = new Border { Classes = { "spec" }, Child = new TextBlock { Text = ability.Text } };
            badge.Classes.Set("warn", !ability.Ok);
            Avalonia.Automation.AutomationProperties.SetAutomationId(badge, "ability_" + ability.Id);
            ToolTip.SetTip(badge, ability.Says);
            MachineRow.Children.Add(badge);
        }
        MachineRow.IsVisible = MachineRow.Children.Count > 0;
        CentreWords();
    }

    void SetTheme(string look)
    {
        _settings.Look = look;
        _settings.Save();
        if (Application.Current is { } app) app.RequestedThemeVariant = App.Variant(look);
        Classes.Set("vault", look == "vault");
        MarkTheme();
        // The lines of the terminal took their brushes from the old theme; so did the cards of ticks.
        Dispatcher.UIThread.Post(Recolour, DispatcherPriority.Background);
        OutdateAll();
        // SETTINGS marks the theme chosen; ABOUT shows the mark made for it.
        FillSheet();
    }

    void MarkTheme()
    {
        ThemeVault.IsChecked = _settings.Look == "vault";
        ThemeDark.IsChecked = _settings.Look == "dark";
        ThemeCode.IsChecked = _settings.Look == "codedark";
        ThemeLight.IsChecked = _settings.Look == "light";
        ThemeButton.IsChecked = false;
    }

    static string Upper(string text) => text.ToUpper(CultureInfo.CurrentCulture);

    /// <summary>The status line: written in Russian by whoever speaks, shown in the language of the window.</summary>
    void SetStatus(string text) => StatusText.Text = Lang.T(text);

    // ------------------------------------------------------------ the start

    async Task StartUp()
    {
        if (!Door.Ready)
        {
            ShowNote(Door.Trouble);
            SetStatus("Движок программы недоступен.");
            return;
        }
        SetStatus("Читаю состав программы…");
        var (told, trouble) = await Door.Describe();
        if (told is null)
        {
            ShowNote(Lang.F("Консольная команда программы не ответила: {0}", trouble));
            SetStatus("Состав программы не прочитан.");
            return;
        }
        _told = told;
        _store = new ValueStore(told.Layout.Shared);
        ShowAbilities();
        StartIo();
        BuildService();
        BuildSections();
        SetStatus("Готово.");
    }

    void ShowNote(string text)
    {
        CardsNote.Text = text;
        CardsNote.IsVisible = true;
    }

    // ------------------------------------------------------------ the header: the service of the program

    void BuildService()
    {
        ServiceRow.Children.Clear();
        if (_told is null) return;
        foreach (var node in _told.Layout.Service)
        {
            var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6 };
            if (Icons.Glyph(node.Icon) is not null) face.Children.Add(Icons.Sign(node.Icon));
            face.Children.Add(new TextBlock { Text = Upper(node.Name) });
            var button = new Button { Classes = { "small" }, Content = face, Margin = new Thickness(0, 0, 4, 0) };
            button.Classes.Set("burn", node.Tone == "burn");
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, "run_" + node.Id);
            ToolTip.SetTip(button, TipOf(node));
            button.Click += (_, _) => Press(node);
            ServiceRow.Children.Add(button);
        }
        // The operations of the working folders of the program: signs beside the paths.
        FolderTools.Children.Clear();
        foreach (var node in _told.Layout.Folders)
        {
            var button = new Button { Classes = { "tool" }, Content = Icons.Sign(Icons.Glyph(node.Icon) is not null ? node.Icon : "trash-2"), Margin = new Thickness(4, 0, 0, 0) };
            button.Classes.Set("burn", node.Tone == "burn");
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, "run_" + node.Id);
            ToolTip.SetTip(button, TipOf(node) + "\n" + FolderLines());
            button.Click += (_, _) => Press(node);
            FolderTools.Children.Add(button);
        }
        ApplyBusy();
    }

    /// <summary>The two working folders of the program by their full paths: what an operation of the folders acts on.</summary>
    string FolderLines() => _told is null ? "" : "input: " + _told.Paths.Input + "\noutput: " + _told.Paths.Output;

    /// <summary>The name of an operation and what it does: the tooltip of its button.</summary>
    static string TipOf(Node node) =>
        node.Tip.Length > 0 ? node.Name + "\n" + node.Tip : node.About.Length > 0 ? node.Name + "\n" + node.About : node.Name;

    // ------------------------------------------------------------ the sections and their pages

    void BuildSections()
    {
        SectionRow.Children.Clear();
        SectionRow.ColumnDefinitions.Clear();
        if (_told is null) return;
        foreach (var section in _told.Layout.Sections)
        {
            var head = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7, HorizontalAlignment = HorizontalAlignment.Center };
            if (Icons.Glyph(section.Icon) is not null) head.Children.Add(Icons.Sign(section.Icon));
            head.Children.Add(new TextBlock { Classes = { "sectionname" }, Text = Upper(section.Name) });
            var face = new StackPanel { VerticalAlignment = VerticalAlignment.Center, Children = { head } };
            // A line that does not fit - a larger font of SETTINGS, a narrow window - ends in an ellipsis, not at the rim.
            if (section.Line.Length > 0) face.Children.Add(new TextBlock { Classes = { "hint" }, Text = section.Line, TextTrimming = TextTrimming.CharacterEllipsis });
            var tab = new ToggleButton { Classes = { "switch", "section" }, Tag = section.Id, Content = face, HorizontalAlignment = HorizontalAlignment.Stretch, MinHeight = 46 };
            Avalonia.Automation.AutomationProperties.SetAutomationId(tab, "section_" + section.Id);
            ToolTip.SetTip(tab, section.Name + "\n" + section.Line);
            tab.Click += (_, _) => SelectSection(section);
            // The sections share the width of the window equally, with a gap between them.
            if (SectionRow.ColumnDefinitions.Count > 0) SectionRow.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(6)));
            SectionRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            Grid.SetColumn(tab, SectionRow.ColumnDefinitions.Count - 1);
            SectionRow.Children.Add(tab);
        }
        var open = _told.Layout.Sections.FirstOrDefault(section => section.Id == _section?.Id) ?? _told.Layout.Sections.FirstOrDefault();
        if (open is not null) SelectSection(open);
    }

    void SelectSection(Section section)
    {
        _section = section;
        foreach (var child in SectionRow.Children)
            if (child is ToggleButton tab) tab.IsChecked = (string?)tab.Tag == section.Id;
        // The pages of the section: a band of switches as large as the sections over it, sharing
        // the width of the left side equally - a sign and a name, no line under them. A name that
        // does not fit an equal share takes its own width (Views\EvenRow.cs).
        PageRow.Children.Clear();
        PageRow.Break = -1;
        foreach (var page in section.Pages)
        {
            var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7, HorizontalAlignment = HorizontalAlignment.Center };
            if (Icons.Glyph(page.Icon) is not null) face.Children.Add(Icons.Sign(page.Icon));
            face.Children.Add(new TextBlock { Classes = { "sectionname" }, Text = Upper(page.Name), TextTrimming = TextTrimming.CharacterEllipsis });
            // What an operation over documents takes, by the marks of the programs of those documents: the violet of the
            // row alone did not say that the button works on a DOCX and not on a picture (the owner, 15.10.2026).
            if (FormatMarks(page.Formats) is { } marks) face.Children.Add(marks);
            var tab = new ToggleButton { Classes = { "switch", "section" }, Tag = page.Id, Content = face, HorizontalAlignment = HorizontalAlignment.Stretch };
            // The pages over the pictures inside documents stand at the right, in their own violet; the row parts the
            // two groups by a gap, and puts the second on a line of its own when both do not fit one (Views\EvenRow.cs).
            bool documents = page.Row == "documents";
            tab.Classes.Set("doc", documents);
            if (documents && PageRow.Break < 0 && PageRow.Children.Count > 0) PageRow.Break = PageRow.Children.Count;
            Avalonia.Automation.AutomationProperties.SetAutomationId(tab, $"page_{section.Id}_{page.Id}");
            // A page that says what it is for says it here; the name alone would repeat the button.
            var formats = string.Join(", ", page.Formats.Select(kind => kind.ToUpperInvariant()));
            if (page.Line.Length > 0 || formats.Length > 0)
                ToolTip.SetTip(tab, string.Join("\n", new[] { page.Name, formats, page.Line }.Where(line => line.Length > 0)));
            tab.Click += (_, _) => SelectPage(page);
            PageRow.Children.Add(tab);
        }
        // A section of one page has nothing to switch.
        PageRow.IsVisible = section.Pages.Count > 1;
        var open = section.Pages.FirstOrDefault(page => _lastPage.TryGetValue(section.Id, out var last) && last == page.Id) ?? section.Pages.FirstOrDefault();
        if (open is not null) SelectPage(open);
    }

    /// <summary>The marks of the formats a page over documents takes - Word for docx, PowerPoint for pptx, Acrobat for pdf -
    /// side by side, the height of a capital letter and a little more; null - the page names none.</summary>
    static StackPanel? FormatMarks(IReadOnlyList<string> formats)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 3, Margin = new Thickness(4, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        foreach (var kind in formats)
        {
            var file = kind switch { "docx" => "word", "pptx" => "powerpoint", "pdf" => "acrobat", _ => "" };
            if (file.Length == 0) continue;
            var mark = new Image
            {
                Source = new Avalonia.Media.Imaging.Bitmap(Avalonia.Platform.AssetLoader.Open(new Uri($"avares://AudionImageTools/Assets/formats/{file}.png"))),
                Width = 16, Height = 16, VerticalAlignment = VerticalAlignment.Center,
            };
            RenderOptions.SetBitmapInterpolationMode(mark, Avalonia.Media.Imaging.BitmapInterpolationMode.HighQuality);
            Avalonia.Automation.AutomationProperties.SetName(mark, kind.ToUpperInvariant());
            row.Children.Add(mark);
        }
        return row.Children.Count > 0 ? row : null;
    }

    void OpenFolder(string folder)
    {
        try
        {
            Directory.CreateDirectory(folder);
            Process.Start(new ProcessStartInfo("explorer.exe") { ArgumentList = { folder }, UseShellExecute = false });
        }
        catch (Exception ex) { SetStatus(Lang.F("Папка не открылась: {0}", ex.Message)); }
    }

    // ------------------------------------------------------------ the terminal

    /// <summary>The text of the terminal since it was last cleared: the copy button gives all of it, up to a limit.</summary>
    readonly StringBuilder _logAll = new();
    const int LogAllLimit = 16_000_000;

    /// <summary>
    /// The panel keeps the last lines of a run and not all of them. It is pages of text one under
    /// another: a text is laid out whole at every line added to it, so new lines go into the last
    /// page while it has room, a full page is never touched again, and the oldest pages leave whole.
    /// </summary>
    const int LogLimit = 5000;
    const int PageLines = 100;
    readonly List<int> _pageLines = new();
    readonly List<int> _pageRuns = new();
    readonly List<(Run Run, Hue Hue)> _logRuns = new();
    int _logShown;
    bool _scrollPosted;
    /// <summary>The colours of the operation that runs: what a line opened is in force on the next.</summary>
    readonly Ansi _ansi = new();

    /// <summary>
    /// Lines into the terminal. A line an operation told is written in the colours its writer gave
    /// it and in no other (Core\Ansi.cs); a line of the window itself - what was run, how it
    /// ended, what the window could not do - in the tone of what it says (Core\LogTones.cs).
    /// </summary>
    void AppendLines(IReadOnlyList<string> lines, bool told = false)
    {
        if (lines.Count == 0) return;
        // The panel follows the new lines while its reader is at the end, and stays where it is
        // when he has gone up to read: asked before the lines are added.
        bool follow = _scrollPosted || LogScroll.Offset.Y + LogScroll.Viewport.Height >= LogScroll.Extent.Height - 40;

        var read = new List<(string Text, Hue Hue)>[lines.Count];
        for (int i = 0; i < lines.Count; i++)
        {
            string plain = lines[i];
            if (told) read[i] = _ansi.Read(lines[i], out plain);
            else
            {
                read[i] = new List<(string, Hue)>();
                // The bounds of a run - its title and its verdict, "===== ..." - stand out in bold.
                if (plain.Length > 0) read[i].Add((plain, new Hue(LogTones.Key(LogTones.Of(plain)), null, plain.StartsWith("===== ", StringComparison.Ordinal), false)));
            }
            _logAll.Append(plain).Append("\r\n");
        }
        if (_logAll.Length > LogAllLimit)
        {
            int cut = LogAllLimit / 4;
            while (cut < _logAll.Length && _logAll[cut - 1] != '\n') cut++;
            _logAll.Remove(0, cut);
        }

        int at = Math.Max(0, lines.Count - LogLimit);
        _logShown += lines.Count - at;
        var pages = LogPages.Children;
        while (at < lines.Count)
        {
            if (_pageLines.Count == 0 || _pageLines[^1] >= PageLines)
            {
                pages.Add(new Controls.LogPage { TextWrapping = TextWrapping.Wrap });
                _pageLines.Add(0);
                _pageRuns.Add(0);
            }
            int held = _pageLines[^1], take = Math.Min(PageLines - held, lines.Count - at);
            // Pieces that stand together and are written the same way are one run.
            var added = new List<Inline>();
            var piece = new StringBuilder();
            var kind = new Hue("LogPlain", null, false, false);
            void Close()
            {
                if (piece.Length == 0) return;
                var run = new Run(piece.ToString()) { Foreground = Ansi.Brush(kind) };
                if (kind.Bold) run.FontWeight = FontWeight.Bold;
                if (kind.Underline) run.TextDecorations = TextDecorations.Underline;
                added.Add(run);
                _logRuns.Add((run, kind));
                piece.Clear();
            }
            for (int i = 0; i < take; i++)
            {
                if (held + i > 0) piece.Append('\n');
                foreach (var (text, hue) in read[at + i])
                {
                    if (hue != kind) Close();
                    kind = hue;
                    piece.Append(text);
                }
            }
            Close();
            var page = (Controls.LogPage)pages[^1];
            (page.Inlines ??= new InlineCollection()).AddRange(added);
            _pageLines[^1] = held + take;
            _pageRuns[^1] += added.Count;
            at += take;
        }

        int gone = 0, lost = 0;
        while (gone < _pageLines.Count - 1 && _logShown - _pageLines[gone] >= LogLimit)
        {
            _logShown -= _pageLines[gone];
            lost += _pageRuns[gone++];
        }
        if (gone > 0)
        {
            pages.RemoveRange(0, gone);
            _pageLines.RemoveRange(0, gone);
            _pageRuns.RemoveRange(0, gone);
            _logRuns.RemoveRange(0, lost);
        }

        if (!follow || _scrollPosted) return;
        _scrollPosted = true;
        Dispatcher.UIThread.Post(() =>
        {
            _scrollPosted = false;
            LogScroll.ScrollToEnd();
        }, DispatcherPriority.Background);
    }

    void ClearLog()
    {
        LogPages.Children.Clear();
        _pageLines.Clear();
        _pageRuns.Clear();
        _logRuns.Clear();
        _logAll.Clear();
        _logShown = 0;
        if (!_runner.Running) _ansi.Reset();
    }

    /// <summary>After a change of the theme the lines already written keep their meaning and take the new colours.</summary>
    void Recolour()
    {
        // A colour a line was given by its writer is the same in every theme.
        foreach (var (run, hue) in _logRuns)
            if (hue.Own is null) run.Foreground = App.Ink(hue.Key);
        if (ActivityRow.IsVisible) ShowActivity(_activity, true);
    }

    async void CopyLog()
    {
        if (_logAll.Length == 0 || Clipboard is not { } clipboard) return;
        try
        {
            await Avalonia.Input.Platform.ClipboardExtensions.SetTextAsync(clipboard, _logAll.ToString());
            Toast.Show(this, Lang.T("Терминал скопирован."));
        }
        catch (Exception ex) { SetStatus(Lang.F("Буфер обмена не принял текст: {0}", ex.Message)); }
    }

    bool _wide;

    /// <summary>The terminal over the whole window - the cards step aside - and back.</summary>
    void ToggleWide()
    {
        _wide = !_wide;
        if (LeftZone.Parent is Grid zones)
        {
            LeftZone.IsVisible = !_wide;
            zones.ColumnDefinitions[0].Width = _wide ? new GridLength(0) : GridLength.Star;
            zones.ColumnDefinitions[2].Width = _wide ? GridLength.Star : new GridLength(560);
        }
        if (WideLogButton.Content is Avalonia.Controls.Shapes.Path sign) sign.Data = Icons.Glyph(_wide ? "minimize-2" : "maximize-2");
    }

    // ------------------------------------------------------------ the end of the window

    void SaveWindow()
    {
        if (WindowState != WindowState.Normal) return;
        _settings.Width = Width;
        _settings.Height = Height;
        _settings.Save();
    }
}
