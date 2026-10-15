using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Platform.Storage;
using AudionImageTools.Core;
using AudionImageTools.Views;

namespace AudionImageTools;

/// <summary>
/// The working paths: what the operations read (the Source - a folder, or one file) and where they
/// write (the Target). Every operation of every section reads these two and no other. The last
/// choice is kept for the next start. A path inside the program is shown from its root; the window
/// keeps the full one.
///
/// The history of paths and its pins are the file the window on NiceGUI kept
/// (config\path_history.json): what was pinned there is pinned here. A path may be pinned, and a
/// path may be taken out of the history.
///
/// What is deleted goes to the Recycle Bin, after a question that names the paths; the guards
/// refuse the root of a drive, the program and a path that is a link (Core\FolderCleaner.cs - the
/// cleaner of Audion Browsers Portable). The disk is not asked on the thread of the window where a
/// folder may be slow to answer.
/// </summary>
public partial class MainWindow
{
    /// <summary>The Source - a folder or one file - as a full path.</summary>
    string _source = "";
    /// <summary>The Target folder, as a full path.</summary>
    string _target = "";

    PathHistory? _history;

    /// <summary>The folders are being cleared or moved: nothing starts and no path changes until that has ended.</summary>
    bool _clearing;

    /// <summary>When a typed path was last refused, and which one: a press made at that very moment does not act on the path before it.</summary>
    DateTime _pathRefusedAt;
    string _pathRefused = "";

    MenuFlyout? _clearMenu;

    string DefaultSource => _told?.Paths.Input is { Length: > 0 } input ? input : Path.Combine(Paths.Root, "input");
    string DefaultTarget => _told?.Paths.Output is { Length: > 0 } output ? output : Path.Combine(Paths.Root, "output");

    /// <summary>The folders of the program that are there to be cleared.</summary>
    string[] WorkingFolders => new[] { DefaultSource, DefaultTarget };

    /// <summary>An operation runs, or the folders are being cleared or moved: the paths stay as they are.</summary>
    bool IoBusy => _runner.Running || _clearing;

    static Task<bool> FolderExists(string path) => Task.Run(() => { try { return Directory.Exists(path); } catch { return false; } });
    static Task<bool> FileExists(string path) => Task.Run(() => { try { return File.Exists(path); } catch { return false; } });

    /// <summary>What the window says of the paths: the status line; a refusal goes into the journal too.</summary>
    void Tell(string text, bool refused = false)
    {
        SetStatus(text);
        if (refused) AppendLines(new[] { "[GUI] " + Lang.T(text) });
    }

    void WireIo()
    {
        PathHistory.Said = line => AppendLines(new[] { line });
        PixelGrid.Field(TargetBox);
        PixelGrid.Field(SourceBox);
        PickSourceButton.Click += (_, _) => PickFolder(source: true);
        PickFileButton.Click += (_, _) => PickFile();
        PickTargetButton.Click += (_, _) => PickFolder(source: false);
        OpenSourceButton.Click += (_, _) => Reveal(_source, make: false);
        OpenTargetButton.Click += (_, _) => Reveal(_target, make: true);
        SourcePinButton.Click += (_, _) => TogglePin(source: true);
        TargetPinButton.Click += (_, _) => TogglePin(source: false);
        WireHistory(SourceHistoryButton, source: true);
        WireHistory(TargetHistoryButton, source: false);
        ResetRouteButton.Click += (_, _) => ResetPaths();
        ListButton.Click += (_, _) => ListSource();
        ToSourceButton.Click += (_, _) => MoveToSource();

        // What to clear is asked first, then the question names the paths.
        var clear = new MenuFlyout
        {
            Placement = PlacementMode.BottomEdgeAlignedLeft,
            Items =
            {
                ClearItem("clear_source", "ИСТОЧНИК: удалить содержимое", source: true, target: false),
                ClearItem("clear_target", "НАЗНАЧЕНИЕ: удалить содержимое", source: false, target: true),
                ClearItem("clear_both", "ИСТОЧНИК и НАЗНАЧЕНИЕ: удалить содержимое обоих", source: true, target: true),
            },
        };
        // The items of a menu are not in the tree of the window, so the switch of the language
        // does not reach them: they take the language in use each time the menu opens.
        clear.Opening += (_, _) =>
        {
            foreach (var item in clear.Items.OfType<MenuItem>()) item.Header = Lang.T(item.Tag as string ?? "");
        };
        // The press that opened this menu took the focus off a path box. A path typed there and
        // refused at that very press put the box back to the path before it - and that folder must
        // not be what the menu then clears.
        clear.Opened += (_, _) =>
        {
            if (!PathJustRefused()) return;
            clear.Hide();
            Tell(Lang.F("очистка отменена - введённый путь не принят: {0}", _pathRefused), refused: true);
        };
        ClearFoldersButton.Flyout = _clearMenu = clear;

        // A path typed by hand is taken when the box is left or Enter is pressed.
        SourceBox.LostFocus += (_, _) => TakeTyped(source: true);
        TargetBox.LostFocus += (_, _) => TakeTyped(source: false);
        SourceBox.KeyDown += (_, e) => { if (e.Key == Key.Enter) { TakeTyped(source: true); Shell.Focus(); e.Handled = true; } };
        TargetBox.KeyDown += (_, e) => { if (e.Key == Key.Enter) { TakeTyped(source: false); Shell.Focus(); e.Handled = true; } };

        // A folder or a file dropped on the window becomes the Source.
        DragDrop.SetAllowDrop(this, true);
        AddHandler(DragDrop.DragOverEvent, (_, e) =>
        {
            e.DragEffects = !IoBusy && e.DataTransfer.Contains(DataFormat.File) ? DragDropEffects.Link : DragDropEffects.None;
            e.Handled = true;
        });
        AddHandler(DragDrop.DropEvent, (_, e) =>
        {
            if (IoBusy) return;
            var path = (e.DataTransfer.TryGetFiles() ?? Array.Empty<IStorageItem>()).Select(item => item.TryGetLocalPath()).FirstOrDefault(item => item is not null);
            if (path is null) return;
            e.Handled = true;
            Dropped(path);
        });
    }

    /// <summary>What was dropped on the window is the Source: a folder, or one file.</summary>
    async void Dropped(string path)
    {
        bool there = await FolderExists(path) || await FileExists(path);
        if (IoBusy) return;
        if (!there) { Tell(Lang.F("источника нет на диске: {0}", path), refused: true); return; }
        Choose(source: true, path);
    }

    MenuItem ClearItem(string id, string text, bool source, bool target)
    {
        // UI Automation presses it as a person does: the peer of a menu item can be invoked since Avalonia 12.1.4.
        var item = new MenuItem { Header = Lang.T(text), Tag = text };
        Avalonia.Automation.AutomationProperties.SetAutomationId(item, id);
        item.Click += (_, _) =>
        {
            // A press that came without a pointer leaves the menu open: closed here either way.
            _clearMenu?.Hide();
            ClearFolders(source, target);
        };
        return item;
    }

    /// <summary>A typed path was refused a moment ago - by the very press that is being handled now. Asked once: the answer is used up.</summary>
    bool PathJustRefused()
    {
        if (DateTime.UtcNow - _pathRefusedAt >= TimeSpan.FromSeconds(2)) return false;
        _pathRefusedAt = default;
        return true;
    }

    /// <summary>
    /// The folders every project has, the history of paths, and the two paths the window opens on:
    /// the ones chosen last, when they are still there; `input` and `output` of the program otherwise.
    /// </summary>
    void StartIo()
    {
        if (_told is null) return;
        foreach (var folder in new[] { _told.Paths.Input, _told.Paths.Output, _told.Paths.Logs, _told.Paths.Report })
        {
            if (string.IsNullOrEmpty(folder)) continue;
            try { Directory.CreateDirectory(folder); }
            catch (Exception ex) { AppendLines(new[] { "[GUI] " + Lang.F("папка не создана: {0} - {1}", folder, ex.Message) }); }
        }
        // A check keeps a history of its own, beside its build: the paths it tries are not the owner's.
        var file = Paths.Released ? Path.Combine(Paths.Config, "path_history.json") : Path.Combine(Paths.Runtime, "path_history.json");
        _history = new PathHistory(file);
        _history.EnsureInitial(DefaultSource, DefaultTarget);

        var source = _settings.SourceFolder.Length > 0 && (Directory.Exists(_settings.SourceFolder) || File.Exists(_settings.SourceFolder)) ? _settings.SourceFolder : DefaultSource;
        var target = _settings.TargetFolder.Length > 0 ? _settings.TargetFolder : DefaultTarget;
        SetSource(source);
        SetTarget(target);
    }

    // ------------------------------------------------------------ the two paths

    void SetSource(string path)
    {
        _source = Paths.Full(path);
        ShowPath(SourceBox, _source);
        ShowPins();
    }

    void SetTarget(string path)
    {
        _target = Paths.Full(path);
        ShowPath(TargetBox, _target);
        ShowPins();
    }

    /// <summary>A path in its box, scrolled to its end: of a long path the last folder says more than the drive.</summary>
    static void ShowPath(TextBox box, string full)
    {
        box.Text = Paths.Short(full);
        box.CaretIndex = box.Text?.Length ?? 0;
    }

    /// <summary>The two paths as they are kept for the next start: a path of the program itself is kept as "the program's own".</summary>
    void KeepPaths()
    {
        _settings.SourceFolder = string.Equals(_source, DefaultSource, StringComparison.OrdinalIgnoreCase) ? "" : _source;
        _settings.TargetFolder = string.Equals(_target, DefaultTarget, StringComparison.OrdinalIgnoreCase) ? "" : _target;
        _settings.Save();
    }

    /// <summary>A path a person chose - picked, typed, dropped or taken from the history: it is set, remembered and kept.</summary>
    void Choose(bool source, string path)
    {
        if (source) SetSource(path); else SetTarget(path);
        _history?.Remember(source, source ? _source : _target);
        ShowPins();
        KeepPaths();
        Tell(Lang.F(source ? "источник: {0}" : "назначение: {0}", Paths.Short(source ? _source : _target)));
    }

    /// <summary>Both paths back to input and output of the program; the history is emptied, the pins stay. No file is touched.</summary>
    void ResetPaths()
    {
        if (IoBusy) { Tell("идёт операция: пути не меняются", refused: true); return; }
        SetSource(DefaultSource);
        SetTarget(DefaultTarget);
        KeepPaths();
        int pins = _history?.ClearKeepPins() ?? 0;
        ShowPins();
        Tell(Lang.F("источник и назначение - input и output программы · закреплений осталось {0}", pins));
    }

    /// <summary>
    /// What was typed into a path box. A Source that is neither a folder nor a file on the disk is
    /// not taken: the box goes back, and the refusal is remembered for a moment - the press that
    /// took the focus off the box may have been a press of a run button, and that run must not go
    /// to the path that stood there before.
    /// </summary>
    void TakeTyped(bool source)
    {
        var box = source ? SourceBox : TargetBox;
        var typed = Paths.Full(box.Text ?? "");
        var held = source ? _source : _target;
        // An empty box is the folder of the program again.
        if (typed.Length == 0) typed = source ? DefaultSource : DefaultTarget;
        if (string.Equals(typed, held, StringComparison.OrdinalIgnoreCase)) { ShowPath(box, held); return; }
        void Refuse(string why)
        {
            ShowPath(box, held);
            _pathRefused = typed;
            _pathRefusedAt = DateTime.UtcNow;
            Tell(why, refused: true);
        }
        if (IoBusy) { Refuse(Lang.T("идёт операция: пути не меняются")); return; }
        if (source && !Directory.Exists(typed) && !File.Exists(typed)) { Refuse(Lang.F("источника нет на диске: {0}", typed)); return; }
        if (!source && File.Exists(typed)) { Refuse(Lang.F("назначение - папка, а это файл: {0}", typed)); return; }
        Choose(source, typed);
    }

    async void PickFolder(bool source)
    {
        if (IoBusy) { Tell("идёт операция: пути не меняются", refused: true); return; }
        var held = source ? _source : _target;
        IStorageFolder? from = null;
        try
        {
            var start = await FolderExists(held) ? held : Path.GetDirectoryName(held);
            if (!string.IsNullOrEmpty(start) && await FolderExists(start)) from = await StorageProvider.TryGetFolderFromPathAsync(start);
        }
        catch { }
        var picked = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions
        {
            Title = Lang.T(source ? "Папка-источник" : "Папка назначения"), AllowMultiple = false, SuggestedStartLocation = from,
        });
        // A run that started while the picker stood open keeps the folders it began with.
        if (IoBusy) return;
        if (picked.Count == 0 || picked[0].TryGetLocalPath() is not { } path) return;
        Choose(source, path);
    }

    /// <summary>One file as the Source: the operation goes over it alone. The file is not copied anywhere.</summary>
    async void PickFile()
    {
        if (IoBusy) { Tell("идёт операция: пути не меняются", refused: true); return; }
        IStorageFolder? from = null;
        try
        {
            var start = await FolderExists(_source) ? _source : Path.GetDirectoryName(_source);
            if (!string.IsNullOrEmpty(start) && await FolderExists(start)) from = await StorageProvider.TryGetFolderFromPathAsync(start);
        }
        catch { }
        var picked = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = Lang.T("Один файл как источник"), AllowMultiple = false, SuggestedStartLocation = from,
        });
        if (IoBusy) return;
        if (picked.Count == 0 || picked[0].TryGetLocalPath() is not { } file) return;
        Choose(source: true, file);
    }

    /// <summary>
    /// A path in Explorer. One file is shown in its folder, marked. The Target is made when it is
    /// not there yet - a result will lie in it; a Source is what lies somewhere already, and is not made.
    /// </summary>
    async void Reveal(string path, bool make)
    {
        bool file = await FileExists(path);
        bool folder = !file && await FolderExists(path);
        if (!file && !folder)
        {
            if (!make) { Tell(Lang.F("источника нет на диске: {0}", path), refused: true); return; }
            try { Directory.CreateDirectory(path); }
            catch (Exception ex) { Tell(Lang.F("папка не создана: {0} - {1}", path, ex.Message), refused: true); return; }
        }
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe")
            {
                Arguments = file ? "/select,\"" + path + "\"" : "\"" + path + "\"",
                UseShellExecute = false,
            });
        }
        catch (Exception ex) { Tell(Lang.F("Папка не открылась: {0}", ex.Message), refused: true); }
    }

    // ------------------------------------------------------------ the history and the pins

    void WireHistory(Button button, bool source)
    {
        var flyout = new Flyout { Placement = PlacementMode.BottomEdgeAlignedRight };
        // Built when it opens: the file may have been changed by another window of the program.
        flyout.Opening += (_, _) => flyout.Content = HistoryList(source, flyout);
        button.Flyout = flyout;
    }

    /// <summary>
    /// The paths used before, the pinned ones first: a press on a line takes its path; the pin of a
    /// line pins it or takes the pin off; the cross takes the line out of the history. The list
    /// stays open while its lines are pinned and removed.
    /// </summary>
    Control HistoryList(bool source, Flyout flyout)
    {
        // As wide as the frame of a list under a button lets a line be: wider, and the cross of a line went past its rim.
        var rows = new StackPanel { Width = 420 };
        var entries = _history?.Entries(source) ?? new List<HistoryEntry>();
        var held = source ? _source : _target;
        var shown = new List<(Button Row, string Path)>();
        foreach (var entry in entries)
        {
            var path = entry.Path;
            var row = new Button
            {
                Classes = { "histrow" },
                Content = new TextBlock { Text = Paths.Short(path), TextTrimming = Avalonia.Media.TextTrimming.CharacterEllipsis },
            };
            row.Classes.Set("current", string.Equals(path, held, StringComparison.OrdinalIgnoreCase));
            ToolTip.SetTip(row, path);
            row.Click += async (_, _) =>
            {
                flyout.Hide();
                if (IoBusy) { Tell("идёт операция: пути не меняются", refused: true); return; }
                if (source && !await FolderExists(path) && !await FileExists(path)) { Tell(Lang.F("источника нет на диске: {0}", path), refused: true); return; }
                if (IoBusy) return;
                Choose(source, path);
            };

            var pin = new Button { Classes = { "tool", "histtool" }, Content = Icons.Sign("pin") };
            pin.Classes.Set("on", entry.Pinned);
            ToolTip.SetTip(pin, Lang.T(entry.Pinned ? "Снять закрепление: путь останется в истории." : "Закрепить: путь стоит первым и переживает сброс."));
            bool pinned = entry.Pinned;
            pin.Click += (_, _) =>
            {
                _history?.SetPinned(source, path, !pinned);
                ShowPins();
                flyout.Content = HistoryList(source, flyout);
            };

            var drop = new Button { Classes = { "tool", "histtool" }, Content = Icons.Sign("x") };
            ToolTip.SetTip(drop, Lang.T("Убрать путь из истории. Папка и файлы не трогаются."));
            drop.Click += (_, _) =>
            {
                _history?.Forget(source, path);
                ShowPins();
                flyout.Content = HistoryList(source, flyout);
            };

            var line = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto") };
            line.Children.Add(row);
            Grid.SetColumn(pin, 1);
            line.Children.Add(pin);
            Grid.SetColumn(drop, 2);
            line.Children.Add(drop);
            rows.Children.Add(line);
            shown.Add((row, path));
        }
        if (entries.Count == 0) rows.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T("история пуста"), Margin = new Thickness(8, 4) });
        // Which of them are still on the disk is found out off the thread of the window and painted when the answer comes.
        _ = MarkGone(shown);
        return new ScrollViewer { MaxHeight = 420, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, Content = rows };
    }

    static async Task MarkGone(List<(Button Row, string Path)> shown)
    {
        var gone = await Task.Run(() => shown.Select(item => { try { return !Directory.Exists(item.Path) && !File.Exists(item.Path); } catch { return true; } }).ToList());
        for (int i = 0; i < shown.Count; i++)
        {
            if (!gone[i]) continue;
            shown[i].Row.Classes.Set("gone", true);
            ToolTip.SetTip(shown[i].Row, Lang.F("нет на диске: {0}", shown[i].Path));
        }
    }

    void TogglePin(bool source)
    {
        if (_history is null) return;
        var path = source ? _source : _target;
        bool pinned = !_history.IsPinned(source, path);
        _history.SetPinned(source, path, pinned);
        ShowPins();
        Tell(pinned ? "путь закреплён" : "закрепление снято");
    }

    /// <summary>The pin of a line is lit while its path is pinned.</summary>
    void ShowPins()
    {
        if (_history is null) return;
        SourcePinButton.Classes.Set("on", _history.IsPinned(true, _source));
        TargetPinButton.Classes.Set("on", _history.IsPinned(false, _target));
    }

    // ------------------------------------------------------------ what lies in the Source

    const int ListedAtMost = 2000;

    /// <summary>What lies in the Source, into the journal: the names of its files, the folders inside it too. Nothing is run.</summary>
    async void ListSource()
    {
        var source = _source;
        ListButton.IsEnabled = false;
        try
        {
            var found = await Task.Run(() =>
            {
                if (File.Exists(source)) return new List<string> { Path.GetFileName(source) };
                if (!Directory.Exists(source)) return null;
                return Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories)
                    .Select(file => Path.GetRelativePath(source, file)).OrderBy(name => name, StringComparer.CurrentCultureIgnoreCase).ToList();
            });
            if (found is null) { Tell(Lang.F("источника нет на диске: {0}", source), refused: true); return; }
            var lines = new List<string> { "[GUI] " + Lang.F("в источнике {0}: файлов {1}", Paths.Short(source), found.Count) };
            lines.AddRange(found.Take(ListedAtMost).Select((name, index) => $"{index + 1,5}  {name}"));
            if (found.Count > ListedAtMost) lines.Add("[GUI] " + Lang.F("показаны первые {0} из {1}", ListedAtMost, found.Count));
            AppendLines(lines);
            Tell(Lang.F("в источнике файлов: {0}", found.Count));
        }
        catch (Exception ex) { Tell(Lang.F("источник не прочитан: {0}", ex.Message), refused: true); }
        finally { ListButton.IsEnabled = true; }
    }

    // ------------------------------------------------------------ clearing

    static string Fate(string path) => FolderCleaner.HasBin(path)
        ? "Удалённое уйдёт в Корзину; о том, чего Корзина не вместит, Windows спросит отдельно."
        : "У этого диска нет Корзины: удалённое не вернуть.";

    /// <summary>
    /// Clearing. Everything is taken before the questions. A folder outside the program is asked
    /// about on its own, whichever line names it: another copy of its pictures may not exist. The
    /// guards refuse the root of a drive, the program and its own folders. While the clearing goes
    /// nothing else starts, no path changes and the window does not close.
    /// </summary>
    async void ClearFolders(bool source, bool target)
    {
        if (_runner.Running) { Tell("идёт другая операция", refused: true); return; }
        if (_clearing) { Tell("очистка уже идёт", refused: true); return; }
        var from = _source;
        var to = _target;
        if (source && await FileExists(from))
        {
            Tell("источник - один файл: очищать нечего. Сам файл программа не удаляет.", refused: true);
            if (!target) return;
            source = false;
        }
        bool same = string.Equals(from, to, StringComparison.OrdinalIgnoreCase);
        var paths = new List<(bool Source, string Path)>();
        if (source) paths.Add((true, from));
        if (target && !(source && same)) paths.Add((false, to));
        var working = WorkingFolders;
        foreach (var (_, path) in paths)
            if (FolderCleaner.Refusal(path, working) is { Length: > 0 } refusal) { Tell(refusal, refused: true); return; }

        // Outside the program: neither its input nor its output, nor a folder inside them.
        var outside = paths.Where(item => !working.Any(folder => IsWithin(item.Path, folder))).ToList();
        if (outside.Count > 0)
        {
            var warning = new List<string> { Lang.T("Будут удалены все файлы и вложенные папки. Другой копии этих файлов у программы нет.") };
            foreach (var (_, path) in outside) { warning.Add(""); warning.Add(path); warning.Add(Lang.T(Fate(path))); }
            if (!await AskDialog.YesNo(this, Lang.T("Очистить папку вне программы?"), string.Join("\n", warning), "burn")) return;
        }
        var lines = new List<string>();
        foreach (var (isSource, path) in paths) lines.Add(Lang.F(isSource ? "ИСТОЧНИК: {0}" : "НАЗНАЧЕНИЕ: {0}", path));
        lines.Add("");
        lines.Add(Lang.T("Сами папки остаются."));
        foreach (var fate in paths.Select(item => Fate(item.Path)).Distinct()) lines.Add(Lang.T(fate));
        if (!await AskDialog.YesNo(this, Lang.T("Удалить содержимое?"), string.Join("\n", lines), "burn")) return;
        // An operation started while the questions stood works with these very folders; a path
        // changed meanwhile is no longer the one the questions named.
        if (IoBusy || !IsVisible) { Tell("идёт другая операция", refused: true); return; }
        if (!string.Equals(from, _source, StringComparison.OrdinalIgnoreCase) || !string.Equals(to, _target, StringComparison.OrdinalIgnoreCase))
        {
            Tell("пути изменились, пока стоял вопрос: ничего не удалено", refused: true);
            return;
        }

        _clearing = true;
        ApplyBusy();
        Tell("очищаю…");
        var window = TryGetPlatformHandle()?.Handle ?? IntPtr.Zero;
        // What is said at the end is what was done: a folder that was not there was not cleared.
        int cleared = 0, absent = 0;
        try
        {
            foreach (var (isSource, path) in paths)
            {
                var done = await Task.Run(() => FolderCleaner.Clear(path, working, window));
                if (done.Kind == "missing")
                {
                    absent++;
                    AppendLines(new[] { "[GUI] " + Lang.F(isSource ? "ИСТОЧНИКА нет на диске, очищать нечего: {0}" : "НАЗНАЧЕНИЯ нет на диске, очищать нечего: {0}", path) });
                    continue;
                }
                cleared++;
                AppendLines(new[] { "[GUI] " + Lang.F(isSource ? "очищен ИСТОЧНИК: {0} · удалено {1}" : "очищено НАЗНАЧЕНИЕ: {0} · удалено {1}", path, done.Removed) });
            }
            if (absent == 0) Tell("очищено");
            else if (cleared == 0) Tell("папки нет на диске: очищать нечего", refused: true);
            else Tell("очищено не всё: одной из папок нет на диске - что именно, сказано в журнале", refused: true);
        }
        catch (OperationCanceledException) { Tell("очистка остановлена в вопросе Windows: удалено не всё", refused: true); }
        // A guard refused at the last moment: of this path nothing was touched.
        catch (InvalidOperationException ex) { Tell(ex.Message, refused: true); }
        catch (Exception ex) { Tell(Lang.F("очистка не вышла: {0} - часть содержимого могла уже уйти", ex.Message), refused: true); }
        finally
        {
            _clearing = false;
            ApplyBusy();
        }
    }

    // ------------------------------------------------------------ the result becomes the source

    /// <summary>
    /// The contents of the Target go into the Source, which is cleared first: the result of one
    /// operation becomes what the next one reads. What lay in the Source goes to the Recycle Bin;
    /// what lies in the Target is moved, not copied - the Target is left empty.
    /// Refused: one folder for both; one of them inside the other; a Source that is one file; the
    /// root of a drive and the program itself, as for a clearing.
    /// </summary>
    async void MoveToSource()
    {
        if (_runner.Running) { Tell("идёт другая операция", refused: true); return; }
        if (_clearing) { Tell("очистка уже идёт", refused: true); return; }
        if (PathJustRefused()) { Tell(Lang.F("перенос отменён - введённый путь не принят: {0}", _pathRefused), refused: true); return; }
        var from = _target;
        var to = _source;
        if (await FileExists(to)) { Tell("источник - один файл: переносить некуда. Выберите папку-источник.", refused: true); return; }
        if (Crossing(from, to) is { Length: > 0 } crossing) { Tell(crossing, refused: true); return; }
        if (!await FolderExists(from)) { Tell(Lang.F("назначения нет на диске: {0}", from), refused: true); return; }
        var working = WorkingFolders;
        foreach (var path in new[] { to, from })
            if (FolderCleaner.Refusal(path, working) is { Length: > 0 } refusal) { Tell(refusal, refused: true); return; }

        int waiting = await Task.Run(() => { try { return Directory.EnumerateFileSystemEntries(from).Count(); } catch { return 0; } });
        if (waiting == 0) { Tell("в назначении пусто: переносить нечего", refused: true); return; }
        // Across drives a folder is copied, and a copy follows a link into wherever it leads - the result would
        // bring in what lies outside it, a loop would copy until the drive is full. Found before anything is
        // emptied (the audit of 15.10.2026, F13).
        if (!SameDrive(from, to) && await Task.Run(() => FirstLink(from)) is { } link)
        {
            Tell(Lang.F("в назначении ссылка на папку или файл: между дисками её не перенести, ничего не тронуто: {0}", link), refused: true);
            return;
        }

        var lines = new List<string>
        {
            Lang.F("Из НАЗНАЧЕНИЯ: {0}", from),
            Lang.F("В ИСТОЧНИК: {0}", to),
            "",
            Lang.T("ИСТОЧНИК сначала очищается: всё, что в нём лежит, удаляется."),
            Lang.T(Fate(to)),
            Lang.T("Затем содержимое НАЗНАЧЕНИЯ переносится в ИСТОЧНИК; НАЗНАЧЕНИЕ остаётся пустым."),
        };
        if (!await AskDialog.YesNo(this, Lang.T("Перенести результат в источник?"), string.Join("\n", lines), "burn")) return;
        if (IoBusy || !IsVisible) { Tell("идёт другая операция", refused: true); return; }
        if (!string.Equals(to, _source, StringComparison.OrdinalIgnoreCase) || !string.Equals(from, _target, StringComparison.OrdinalIgnoreCase))
        {
            Tell("пути изменились, пока стоял вопрос: ничего не тронуто", refused: true);
            return;
        }
        // Once more right before the Source is emptied: a link may have been made while the question stood.
        if (Crossing(from, to) is { Length: > 0 } now) { Tell(now, refused: true); return; }

        _clearing = true;
        ApplyBusy();
        Tell("переношу результат в источник…");
        var window = TryGetPlatformHandle()?.Handle ?? IntPtr.Zero;
        try
        {
            var cleared = await Task.Run(() =>
            {
                Directory.CreateDirectory(to);
                return FolderCleaner.Clear(to, working, window);
            });
            int moved = await Task.Run(() => MoveContents(from, to));
            AppendLines(new[] { "[GUI] " + Lang.F("результат перенесён в источник: из источника убрано записей {0}, перенесено записей {1} · {2} → {3}", cleared.Removed, moved, Paths.Short(from), Paths.Short(to)) });
            Tell(Lang.F("перенесено в источник, записей: {0}", moved));
        }
        catch (OperationCanceledException) { Tell("перенос остановлен в вопросе Windows: источник очищен не весь, из назначения ничего не взято", refused: true); }
        catch (InvalidOperationException ex) { Tell(ex.Message, refused: true); }
        catch (Exception ex) { Tell(Lang.F("перенос не вышел: {0} - часть файлов могла уже переехать, остальное лежит в назначении", ex.Message), refused: true); }
        finally
        {
            _clearing = false;
            ApplyBusy();
        }
    }

    /// <summary>
    /// What lies in one folder is moved into another, entry by entry; how many entries of the first
    /// level went. On one drive a move is a rename; across drives a folder is copied and then removed.
    /// </summary>
    static int MoveContents(string from, string to)
    {
        int moved = 0;
        bool sameDrive = SameDrive(from, to);
        foreach (var entry in Directory.EnumerateFileSystemEntries(from).ToList())
        {
            var target = Path.Combine(to, Path.GetFileName(entry));
            if (File.Exists(entry)) File.Move(entry, target, overwrite: true);
            else if (sameDrive) Directory.Move(entry, target);
            else
            {
                CopyFolder(entry, target);
                Directory.Delete(entry, recursive: true);
            }
            moved++;
        }
        return moved;
    }

    static void CopyFolder(string from, string to)
    {
        // Never into a link: FirstLink refused the move before; this is the guard behind it.
        if (new DirectoryInfo(from).Attributes.HasFlag(FileAttributes.ReparsePoint))
            throw new InvalidOperationException(Lang.F("ссылка на папку не переносится между дисками: {0}", from));
        Directory.CreateDirectory(to);
        foreach (var file in Directory.EnumerateFiles(from)) File.Copy(file, Path.Combine(to, Path.GetFileName(file)), overwrite: true);
        foreach (var folder in Directory.EnumerateDirectories(from)) CopyFolder(folder, Path.Combine(to, Path.GetFileName(folder)));
    }

    /// <summary>
    /// Why the result may not be moved into the Source; "" - it may. Judged by the folders the paths really lead
    /// to (FolderCleaner.Real): through a junction in a parent folder two different strings are one folder, and
    /// the Source emptied first took the result with it (the audit of 15.10.2026, F05).
    /// </summary>
    static string Crossing(string from, string to)
    {
        var result = FolderCleaner.Real(from);
        var source = FolderCleaner.Real(to);
        if (string.Equals(result, source, StringComparison.OrdinalIgnoreCase)) return "источник и назначение - одна папка: переносить нечего";
        if (IsWithin(source, result)) return "источник лежит внутри назначения: перенос стёр бы его самого";
        if (IsWithin(result, source)) return "назначение лежит внутри источника: очистка источника стёрла бы результат";
        return "";
    }

    static bool SameDrive(string from, string to) =>
        string.Equals(Path.GetPathRoot(FolderCleaner.Real(from)), Path.GetPathRoot(FolderCleaner.Real(to)), StringComparison.OrdinalIgnoreCase);

    /// <summary>The first link - a junction, a symbolic link - in a folder and the folders under it, never entered; null - none.
    /// A folder that cannot be read is named as well: what is not seen is not moved across drives.</summary>
    static string? FirstLink(string folder)
    {
        var pending = new Stack<string>();
        pending.Push(folder);
        while (pending.Count > 0)
        {
            var current = pending.Pop();
            try
            {
                foreach (var entry in new DirectoryInfo(current).EnumerateFileSystemInfos())
                {
                    if (entry.Attributes.HasFlag(FileAttributes.ReparsePoint)) return entry.FullName;
                    if (entry is DirectoryInfo) pending.Push(entry.FullName);
                }
            }
            catch (Exception) { return current; }
        }
        return null;
    }

    static bool IsWithin(string path, string folder)
    {
        try
        {
            var full = Path.GetFullPath(path).TrimEnd('\\', '/');
            var home = Path.GetFullPath(folder).TrimEnd('\\', '/');
            return string.Equals(full, home, StringComparison.OrdinalIgnoreCase) || full.StartsWith(home + "\\", StringComparison.OrdinalIgnoreCase);
        }
        catch { return false; }
    }

    /// <summary>The controls of the paths answer only while nothing runs and nothing is being cleared.</summary>
    void ApplyIoBusy()
    {
        bool free = !IoBusy;
        foreach (var control in new Control[] { SourceBox, TargetBox, PickSourceButton, PickFileButton, PickTargetButton, SourceHistoryButton, TargetHistoryButton,
                                                ResetRouteButton, ToSourceButton, ClearFoldersButton })
            control.IsEnabled = free;
    }
}
