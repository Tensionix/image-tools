using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;
using AudionImageTools.Core;

namespace AudionImageTools.Views;

/// <summary>
/// The form of an operation, drawn by the keys of the manifest. A field is in sight while its
/// conditions hold (`visible_if`, `hidden_if` and the rest - Core\Conditions.cs); the fields stand
/// in the blocks the manifest names (`section`). A choice is a row of switches, never a drop-down
/// list. The form keeps nothing itself: every control reads and writes the <see cref="Values"/> of
/// its page by the id of its field - the operations of one page share a field, two pages do not.
/// </summary>
public sealed class Form
{
    readonly Values _values;
    /// <summary>What a change of a field that decides the shape of the form asks for: the cards are built again.</summary>
    readonly Action _rebuild;

    /// <summary>What repaints the controls of a field, by the id of the field: a form built now, gone at the next build.</summary>
    readonly Dictionary<string, List<Action>> _cells = new();
    /// <summary>The fields whose change alters what is in sight.</summary>
    readonly HashSet<string> _shaping = new();

    /// <summary>Kinds of field met while building that the form cannot draw.</summary>
    public HashSet<string> Unknown { get; } = new();

    public Form(Values values, Action rebuild)
    {
        _values = values;
        _rebuild = rebuild;
        _values.Changed += _heard = id =>
        {
            if (_shaping.Contains(id)) { _rebuild(); return; }
            if (!_cells.TryGetValue(id, out var repaint)) return;
            foreach (var action in repaint.ToArray()) action();
        };
    }

    readonly Action<string> _heard;

    /// <summary>
    /// The page is thrown away - the language changed. Its values live on for the page built anew,
    /// so this form stops hearing them: it would go on repainting controls nobody sees.
    /// </summary>
    public void Detach() => _values.Changed -= _heard;

    /// <summary>A new build of the cards begins: the controls of the last one are forgotten.</summary>
    public void Forget()
    {
        _cells.Clear();
        _shaping.Clear();
        _build++;
    }

    /// <summary>The number of the build of the cards in hand: rows left to build for an older one are dropped.</summary>
    int _build;

    /// <summary>
    /// The rows of a long list below the first screen are built a row at a time, while nothing else
    /// goes on. False - the whole form at once: a form built again in place must be as tall as it
    /// was, or the page would jump.
    /// </summary>
    public bool Lazy { get; set; } = true;

    /// <summary>Raised when a row built later has joined the form: its words want centring too.</summary>
    public Action? Grown { get; set; }

    /// <summary>The form of an operation over the pictures inside documents: its blocks wear the violet stripe.</summary>
    public bool Documents { get; set; }

    void Watch(Field field, Action repaint)
    {
        if (!_cells.TryGetValue(field.Id, out var list)) _cells[field.Id] = list = new List<Action>();
        list.Add(repaint);
        repaint();
    }

    static string Upper(string text) => text.ToUpper(CultureInfo.CurrentCulture);

    public bool InSight(Field field) =>
        !field.Hidden && !FieldKinds.Matches(field.HiddenWhen, _values.Get)
        && (field.VisibleWhen is not { Count: > 0 } || FieldKinds.Matches(field.VisibleWhen, _values.Get))
        && Conditions.Visible(field, _values);

    /// <summary>In sight and not to be set: "Quality" while the format ticked has none.</summary>
    public bool Off(Field field) => Conditions.Disabled(field, _values);

    public bool InSight(Dictionary<string, JsonElement>? condition) =>
        condition is not { Count: > 0 } || FieldKinds.Matches(condition, _values.Get);

    /// <summary>The conditions of a card name these fields: when one of them changes, the card is another card.</summary>
    public void Shapes(IEnumerable<string> ids)
    {
        foreach (var id in ids) _shaping.Add(id);
    }

    // ------------------------------------------------------------ the form

    /// <summary>The fields of an operation in sight, block by block in the order the manifest first names each block.</summary>
    public Control Build(Node node)
    {
        _values.Learn(node.Fields);
        foreach (var field in node.Fields)
        {
            if (field.VisibleWhen is not null) Shapes(field.VisibleWhen.Keys);
            if (field.HiddenWhen is not null) Shapes(field.HiddenWhen.Keys);
            Shapes(Conditions.FieldsOf(field));
        }
        var host = new StackPanel { Spacing = 6 };
        // The names of the fields of every block take one width: the controls begin on one line.
        Grid.SetIsSharedSizeScope(host, true);
        var seen = node.Fields.Where(InSight).ToList();
        foreach (var group in InOrder(seen.GroupBy(field => field.Group), node.Groups))
        {
            var body = new StackPanel();
            var name = GroupName(group.Key);
            // The names of the first choices of the block took the line of its name: the block is not named a second time.
            bool headed = false;
            WrapPanel? flags = null;
            var lists = new List<Field>();
            var lines = new List<Field>();
            void Lists()
            {
                if (lists.Count > 0) body.Children.Add(Groups(lists));
                lists.Clear();
            }
            void Lines()
            {
                if (lines.Count == 0) return;
                // Only the fields a named block begins with: there the line of the name is theirs.
                body.Children.Add(TwoColumns(lines, name.Length > 0 && body.Children.Count == 0, out bool took));
                headed |= took;
                lines.Clear();
            }
            foreach (var field in group)
            {
                if (!FieldKinds.Known.Contains(field.Kind)) { Unknown.Add($"{field.Id}: {field.Kind}"); continue; }
                if (field.Kind == "checkboxes") { flags = null; Lines(); lists.Add(field); continue; }
                Lists();
                if (field.Kind == "checkbox")
                {
                    Lines();
                    // Flags that follow one another stand in one row.
                    if (flags is null) body.Children.Add(flags = new WrapPanel { Orientation = Orientation.Horizontal });
                    flags.Children.Add(Flag(field));
                    continue;
                }
                flags = null;
                // A text of many lines takes the whole width; the fields of one line share it by two.
                if (field.Kind == "textarea") { Lines(); body.Children.Add(Cell(field)); }
                else lines.Add(field);
            }
            Lists();
            Lines();
            if (body.Children.Count == 0) continue;
            if (name.Length > 0 && !headed) body.Children.Insert(0, new TextBlock { Classes = { "grp" }, Text = Upper(name) });
            // A block that is nothing but groups of ticks needs no frame around their frames.
            bool onlyLists = group.All(field => field.Kind == "checkboxes");
            host.Children.Add(onlyLists && name.Length == 0 ? body : new Border { Classes = { "grp" }, Child = Striped(body, group.Key, Documents) });
        }
        return host;
    }

    /// <summary>
    /// Fields of one line that follow one another, in two columns with a rule between them: the
    /// first half at the left, the rest at the right (the owner of Audion Get Tools, 10.10.2026:
    /// "look how much room there is at the right ... in two columns, parted by a stick"). One
    /// field, or a block too narrow for two rows of switches side by side, stays one column.
    ///
    /// With <paramref name="heads"/> the first field of each column gives its name to the line
    /// where the name of the block stood, and its row of switches takes the whole width of the
    /// column (the owner, 11.10.2026: "they should simply stand at the top in place of the name of
    /// the block, on the same line: the chips get more room, and there is no gaping emptiness").
    /// Only when every column begins with a choice that has a name: the names then stand on one line.
    ///
    /// The row under such a name stands at the indent of the rows under it (the owner, the same
    /// day: "the upper rows of buttons must be at the same indent as the lower ones"): in the
    /// column of the values when its column has rows with names at their left, at the rim when it
    /// has none.
    /// </summary>
    Control TwoColumns(List<Field> fields, bool heads, out bool took)
    {
        int half = fields.Count < 2 ? fields.Count : (fields.Count + 1) / 2;
        static bool Heads(Field field) => field.Kind is "radio" or "select" && field.Name.Length > 0;
        bool second = half < fields.Count;
        took = heads && Heads(fields[0]) && (!second || Heads(fields[half]));
        var lines = new List<Control>();
        for (int i = 0; i < fields.Count; i++)
        {
            var field = fields[i];
            if (!took || (i != 0 && i != half)) { lines.Add(Cell(field)); continue; }
            var head = new TextBlock { Classes = { "grp" }, Text = Upper(field.Name) };
            if (field.Tip.Length > 0) ToolTip.SetTip(head, field.Tip);
            Control row = Choice(field);
            // The rows under it in its column that carry a name at their left: this row lines up with their switches.
            var under = i == 0 ? fields.Skip(1).Take(half - 1) : fields.Skip(half + 1);
            if (under.Any(other => other.Name.Length > 0))
            {
                var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
                line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
                Grid.SetColumn(row, 1);
                line.Children.Add(row);
                row = line;
            }
            row.Margin = new Thickness(0, 0, 0, 2);
            lines.Add(new StackPanel { Children = { head, row } });
        }
        var left = new StackPanel();
        if (lines.Count < 2)
        {
            foreach (var line in lines) left.Children.Add(line);
            return left;
        }
        var right = new StackPanel();
        for (int i = 0; i < lines.Count; i++) (i < half ? left : right).Children.Add(lines[i]);
        var rule = new Border { Width = 1, Margin = new Thickness(0, 1, 0, 5), HorizontalAlignment = HorizontalAlignment.Center }.Ink(Border.BackgroundProperty, "SepInk");
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,21,*"), RowDefinitions = new RowDefinitions("Auto,Auto") };
        Grid.SetColumn(rule, 1);
        grid.Children.Add(left);
        grid.Children.Add(rule);
        grid.Children.Add(right);
        bool? wide = null;
        void Fit(double width)
        {
            bool now = width >= TwoColumnsFrom;
            if (wide == now) return;
            wide = now;
            rule.IsVisible = now;
            Grid.SetColumn(right, now ? 2 : 0);
            Grid.SetRow(right, now ? 0 : 1);
            Grid.SetColumnSpan(left, now ? 1 : 3);
            Grid.SetColumnSpan(right, now ? 1 : 3);
        }
        Fit(TwoColumnsFrom);
        grid.SizeChanged += (_, e) => Fit(e.NewSize.Width);
        return grid;
    }

    /// <summary>The width from which a block holds two columns of fields: a name and its row of switches, twice.</summary>
    const double TwoColumnsFrom = 760;

    /// <summary>
    /// The cards of a list on columns of equal width, row by row; a row is as tall as the tallest
    /// card in it - a line that wrapped makes its own row taller, not every card of the list.
    /// </summary>
    static void Lay(Grid grid, int columns)
    {
        columns = Math.Max(1, columns);
        int rows = Math.Max(1, (grid.Children.Count + columns - 1) / columns);
        if (grid.ColumnDefinitions.Count != columns)
        {
            grid.ColumnDefinitions.Clear();
            for (int c = 0; c < columns; c++) grid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        }
        if (grid.RowDefinitions.Count != rows)
        {
            grid.RowDefinitions.Clear();
            for (int r = 0; r < rows; r++) grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        }
        for (int i = 0; i < grid.Children.Count; i++)
        {
            Grid.SetColumn(grid.Children[i], i % columns);
            Grid.SetRow(grid.Children[i], i / columns);
        }
    }

    /// <summary>The gap between two columns of cards with a rule in its middle: eight, the rule, eight.</summary>
    const double RuledGap = 17;

    /// <summary>What a field is called to the person: its own name, or - for a list the manifest gives none - the name of its block.</summary>
    public static string NameOf(Field field) => field.Name.Length > 0 ? field.Name : GroupName(field.Group);

    /// <summary>The name of a block of the form, in the language of the window, as the window on NiceGUI named them; "" - the block needs none.</summary>
    static string GroupName(string group) => group switch
    {
        "parameters" => Lang.T("Параметры"),
        "format" => Lang.T("Формат"),
        "output" => Lang.T("Результат"),
        "source" => Lang.T("Источник"),
        "preset" or "thumbnail" => Lang.T("Миниатюра"),
        "encoding" => Lang.T("Кодирование"),
        "profile" => Lang.T("Профиль"),
        "run" => Lang.T("Запуск"),
        "advanced" => Lang.T("Дополнительно"),
        "" => "",
        _ => char.ToUpperInvariant(group[0]) + group[1..].Replace('_', ' '),
    };

    Control Cell(Field field)
    {
        Control control = field.Kind switch
        {
            "radio" or "select" => Choice(field),
            "number" => NumberBox(field),
            "slider" => SliderBox(field),
            "quality" => Quality(field),
            "rgb_color" => Rgb(field),
            // As tall as the manifest says; five lines where it says nothing. The box grows as it is typed in.
            "textarea" => TextBox(field, lines: field.Rows > 0 ? field.Rows : 5),
            _ => TextBox(field, lines: 1),
        };
        // Switched off by the values of other fields: in sight, greyed, not to be set.
        control.IsEnabled = !Off(field);
        if (field.Name.Length == 0) return control;
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Margin = new Thickness(0, 0, 0, 2) };
        line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
        var label = new TextBlock { Classes = { "fieldname" }, Text = field.Name, Margin = new Thickness(1, 0, 14, 4), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 210, TextWrapping = TextWrapping.Wrap };
        if (field.Tip.Length > 0) ToolTip.SetTip(label, field.Tip);
        line.Children.Add(label);
        Grid.SetColumn(control, 1);
        line.Children.Add(control);
        return line;
    }

    // ------------------------------------------------------------ controls

    static readonly Geometry Tick = Geometry.Parse("M 1.5,5 L 4,7.5 L 8.5,2.5");

    static Border TickBox() => new()
    {
        Classes = { "tickbox" },
        Child = new Avalonia.Controls.Shapes.Path { Classes = { "tick" }, Data = Tick },
    };

    static Control Faced(string text) => new StackPanel
    {
        Orientation = Orientation.Horizontal, Spacing = 7,
        Children = { TickBox(), new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center } },
    };

    ToggleButton Flag(Field field)
    {
        var flag = new ToggleButton { Classes = { "switch" }, Content = Faced(field.Name), Margin = new Thickness(0, 0, 6, 6) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(flag, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(flag, field.Tip);
        flag.Click += (_, _) => _values.Set(field, flag.IsChecked == true ? "true" : "false");
        Watch(field, () => flag.IsChecked = _values.IsOn(field));
        flag.IsEnabled = !Off(field);
        return flag;
    }

    /// <summary>A choice of a few: a row of switches, one of them on.</summary>
    Control Choice(Field field)
    {
        var row = new WrapPanel { Orientation = Orientation.Horizontal };
        var buttons = new List<(ToggleButton Button, string Key)>();
        foreach (var option in field.Options.Where(option => !option.Header))
        {
            var button = new ToggleButton { Classes = { "switch" }, Content = Named(option), Margin = new Thickness(0, 0, 4, 4) };
            ChoiceTones.Wear(button, option.Tone);
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"field_{field.Id}_{option.Key}");
            var tip = option.Tip.Length > 0 ? option.Tip : field.Tip;
            if (tip.Length > 0) ToolTip.SetTip(button, tip);
            var key = option.Key;
            button.Click += (_, _) =>
            {
                _values.Set(field, key);
                // A press on the chosen one must not switch it off: one of the row is always on.
                button.IsChecked = _values.Get(field) == key;
            };
            buttons.Add((button, key));
            row.Children.Add(button);
        }
        Watch(field, () =>
        {
            var current = _values.Get(field);
            foreach (var (button, key) in buttons) button.IsChecked = key == current;
        });
        return row;
    }

    /// <summary>
    /// The blocks of a form in the order the layout names (`groups` of the card): those named first,
    /// as named; a block not named stands after them, as its fields come.
    /// </summary>
    public static List<T> InOrder<T>(IEnumerable<T> blocks, IReadOnlyList<string> order) where T : IGrouping<string, Field>
    {
        var listed = blocks.ToList();
        if (order.Count == 0) return listed;
        int At(T block)
        {
            for (int i = 0; i < order.Count; i++)
                if (order[i] == block.Key) return i;
            return int.MaxValue;
        }
        // A stable sort: blocks of one rank keep the order of their fields.
        return listed.OrderBy(At).ToList();
    }

    /// <summary>
    /// Lists of ticks that follow one another, as framed groups in rows - the way Audion Disk Tools
    /// lays out its masks: a long group takes a row to itself, short ones share a row by two.
    /// </summary>
    Control Groups(List<Field> fields)
    {
        var host = new StackPanel();
        // How many groups share a row: one that is long or has long names stands alone.
        bool Wide(int at) => Real(fields[at].Options).Count > 12 || Longest(fields[at].Options) > 30 || fields[at].Options.Any(option => option.Header);
        var rows = new List<(int First, int Count)>();
        for (int i = 0; i < fields.Count;)
        {
            int perRow = Wide(i) || i + 1 >= fields.Count || Wide(i + 1) ? 1 : 2;
            rows.Add((i, perRow));
            i += perRow;
        }
        Control Row((int First, int Count) at)
        {
            var row = new Grid();
            for (int c = 0; c < at.Count; c++)
            {
                row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
                var block = Ticks(fields[at.First + c]);
                Grid.SetColumn(block, c);
                row.Children.Add(block);
            }
            return row;
        }
        // The first screen at once - some forty cards; the rows under it one by one, each when the
        // window has nothing else to do. A build that came after drops what is left of this one.
        int build = _build, next = 0, cards = 0;
        for (; next < rows.Count && (!Lazy || cards < 40); next++)
        {
            host.Children.Add(Row(rows[next]));
            for (int c = 0; c < rows[next].Count; c++) cards += Real(fields[rows[next].First + c].Options).Count;
        }
        void Later()
        {
            if (build != _build || next >= rows.Count) return;
            host.Children.Add(Row(rows[next++]));
            Grown?.Invoke();
            Dispatcher.UIThread.Post(Later, DispatcherPriority.Background);
        }
        if (next < rows.Count) Dispatcher.UIThread.Post(Later, DispatcherPriority.Background);
        return host;
    }

    static List<Option> Real(List<Option> options) => options.Where(option => !option.Header).ToList();

    static int Longest(List<Option> options) => Real(options).Select(option => option.Name.Length).DefaultIfEmpty(0).Max();

    /// <summary>
    /// A group of ticks: a framed block with its name, how many of it are ticked, ALL and NONE,
    /// and its ticks as cards - how they are laid out is told where it is decided, below. The
    /// value is the list of those that are on.
    /// </summary>
    Control Ticks(Field field)
    {
        var options = field.Options;
        var column = new StackPanel();
        // A long name wraps, and the count with ALL and NONE goes under it: on one line it pushed them past the rim.
        var title = new TextBlock { Classes = { "blockname" }, Text = field.Name, TextWrapping = TextWrapping.Wrap };
        if (field.Tip.Length > 0) ToolTip.SetTip(title, field.Tip);
        var head = new WrapPanel { Orientation = Orientation.Horizontal, ItemSpacing = 8, LineSpacing = 2, Margin = new Thickness(0, 0, 0, 6), MinHeight = 20 };
        // A list the manifest gives no name is named by its block: its head begins with the count.
        if (field.Name.Length > 0) head.Children.Add(title);
        column.Children.Add(head);
        var block = new Border { Classes = { "block", "ticks" }, Child = column };
        var real = Real(options);
        if (real.Count == 0)
        {
            column.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T("список пуст") });
            return block;
        }
        // The layout - known once the block has its width. The room a card needs is its tick, its
        // words in the font of the cards and the gap after it.
        //   Short names: as many columns as hold the longest name whole, four at most. A name is never cut to fit.
        //   Long lines without headings: two columns of cards with a rule between them.
        //   A list under headings: every heading is a block of its own, and the blocks stand in two
        //   stacks by turns - the first at the left, the second at the right, the third under the
        //   first. Inside a block the cards stand one under another.
        //   A line too long for its place is set a point smaller when that is what it takes, and
        //   wraps inside its card when even that is not enough. Nothing is cut.
        int longest = Longest(options);
        bool lines = longest > 30, grouped = options.Any(option => option.Header && !option.Note);
        double usual = App.SizeOf("FontCard", 11.5);
        // A letter of the font of the window is 0.61 of its size wide; short names keep the measure
        // their columns were laid out by (6.4 at the usual size).
        double Need(double points) => 20 + longest * (lines ? points * 0.612 : 6.4 * points / 11.5) + 26;
        var sheets = new List<(Panel Host, Grid Grid, Border Rule)>();
        var cards = new List<(Border Card, ToggleButton Tick, TextBlock Name)>();
        var blocks = new List<Border>();
        // How many cards stand under each heading: what the two stacks are balanced by.
        var counts = new List<int>();
        StackPanel leftStack = new(), rightStack = new();
        Grid.SetColumn(rightStack, 2);
        var stacks = new Grid { ColumnDefinitions = new ColumnDefinitions("*,4,*"), Children = { leftStack, rightStack } };
        int columns = 1;
        bool smaller = false, wraps = false, pair = false;
        bool? stacked = null;
        int stackedBy = 0;
        void Stack()
        {
            if (stacked == pair && stackedBy == columns) return;
            (stacked, stackedBy) = (pair, columns);
            leftStack.Children.Clear();
            rightStack.Children.Clear();
            // Each block to the column that is shorter so far (Core\Columns.cs).
            var right = Columns.Right(counts.Select(count => Columns.Height(count, columns)).ToList());
            for (int i = 0; i < blocks.Count; i++) (pair && right[i] ? rightStack : leftStack).Children.Add(blocks[i]);
            Grid.SetColumnSpan(leftStack, pair ? 1 : 3);
            rightStack.IsVisible = pair;
        }
        void Dress()
        {
            bool ruled = lines && !grouped && columns == 2;
            foreach (var (host, sheet, rule) in sheets)
            {
                Lay(sheet, columns);
                rule.IsVisible = ruled && sheet.Children.Count > 1;
                // The gap after the last column is as wide as the gap between the columns: taken back, so both edges of the list stand alike.
                host.Margin = ruled ? new Thickness(0, 0, 8 - RuledGap, 0) : default;
            }
            foreach (var (card, tick, name) in cards)
            {
                if (ruled) card.Margin = new Thickness(0, 0, RuledGap, 8);
                else card.ClearValue(Layoutable.MarginProperty);
                if (smaller) tick.FontSize = usual - 1;
                else tick.ClearValue(TemplatedControl.FontSizeProperty);
                name.TextWrapping = wraps ? TextWrapping.Wrap : TextWrapping.NoWrap;
                // Two lines of words fill a card to its rims: they are given room over and under them.
                name.Margin = wraps ? new Thickness(7, 4, 0, 4) : new Thickness(7, 0, 0, 0);
            }
            if (grouped) Stack();
        }
        void Fit(double width)
        {
            if (width <= 0) return;
            double room = width - 16;
            int fit;
            bool small = false, wrap = false, two = false;
            if (grouped)
            {
                two = blocks.Count > 1 && room >= TwoColumnsFrom - 100;
                double inside = (two ? (room - 4) / 2 : room) - 14;
                if (!lines) fit = Math.Clamp((int)(inside / Need(usual)), 1, 4);
                else
                {
                    fit = 1;
                    small = inside < Need(usual);
                    wrap = inside < Need(usual - 1);
                }
            }
            else if (!lines) fit = Math.Clamp((int)(room / Need(usual)), 1, 4);
            else if (room >= 2 * Need(usual)) fit = 2;
            else if (room >= 2 * Need(usual - 1)) { fit = 2; small = true; }
            else if (room >= TwoColumnsFrom - 100) { fit = 2; small = true; wrap = true; }
            else fit = 1;
            fit = Math.Min(fit, real.Count);
            if (fit == columns && small == smaller && wrap == wraps && two == pair) return;
            (columns, smaller, wraps, pair) = (fit, small, wrap, two);
            Dress();
        }
        block.SizeChanged += (_, e) => Fit(e.NewSize.Width);
        var ticks = new List<(ToggleButton Tick, string Key)>();
        // A heading opens a block of its own; cards before any heading stand in the list itself.
        Panel into = column;
        Grid? grid = null;
        foreach (var option in options)
        {
            if (option.Header && option.Note)
            {
                // What the list is, in words, across the whole of it.
                column.Children.Add(new TextBlock { Classes = { "note" }, Text = option.Name, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(1, 0, 8, 7) });
                continue;
            }
            if (option.Header)
            {
                var body = new StackPanel();
                body.Children.Add(new TextBlock { Classes = { "grp" }, Text = Upper(option.Name) });
                if (blocks.Count == 0) column.Children.Add(stacks);
                blocks.Add(new Border { Classes = { "grp", "inner" }, Child = body });
                counts.Add(0);
                into = body;
                grid = null;
                continue;
            }
            if (grid is null)
            {
                grid = new Grid();
                // The rule between two columns of lines: in the middle of the gap the cards leave.
                var rule = new Border { Width = 1, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 1, RuledGap, 9), IsVisible = false }
                    .Ink(Border.BackgroundProperty, "SepInk");
                var sheet = new Panel { Children = { grid, rule } };
                into.Children.Add(sheet);
                sheets.Add((sheet, grid, rule));
            }
            // The tone of the card as plain brushes on its parts; what the pointer and the tick change is changed here.
            var look = Tones.Of(option.Tone.Length > 0 ? option.Tone : "plain");
            var box = TickBox();
            box.BorderBrush = look.BoxRim;
            box.Background = look.Box;
            var words = new TextBlock { Text = option.Name, Foreground = look.Ink, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(7, 0, 0, 0) };
            Grid.SetColumn(words, 1);
            // A grid, not a row: the words are told how wide they may be, so a line too long for its card can wrap.
            var face = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Children = { box, words } };
            var tick = new ToggleButton { Classes = { "ptick" }, Content = face };
            Avalonia.Automation.AutomationProperties.SetAutomationId(tick, $"field_{field.Id}_{option.Key}");
            var tip = option.Tip.Length > 0 ? option.Tip : field.Tip;
            if (tip.Length > 0) ToolTip.SetTip(tick, tip);
            ticks.Add((tick, option.Key));
            // The card: its rim and its ground in the tone the manifest names, the tick and the name.
            var card = new Border { Classes = { "ptile" }, Child = tick, BorderBrush = look.Rim, Background = look.Wash };
            void Wear()
            {
                bool on = tick.IsChecked == true, over = card.IsPointerOver;
                card.BorderBrush = on ? look.RimOn : over ? look.RimOver : look.Rim;
                card.Background = on ? look.WashOn : over ? look.WashOver : look.Wash;
                box.BorderBrush = on ? look.FillRim : look.BoxRim;
                box.Background = on ? look.Fill : look.Box;
            }
            tick.IsCheckedChanged += (_, _) => Wear();
            card.PointerEntered += (_, _) => Wear();
            card.PointerExited += (_, _) => Wear();
            cards.Add((card, tick, words));
            if (counts.Count > 0) counts[^1]++;
            grid.Children.Add(card);
        }
        Dress();
        void Take() => _values.Set(field, string.Join(Values.ListSeparator, ticks.Where(item => item.Tick.IsChecked == true).Select(item => item.Key)));
        foreach (var (tick, _) in ticks) tick.Click += (_, _) => Take();
        Watch(field, () =>
        {
            var picked = _values.Picked(field);
            foreach (var (tick, key) in ticks) tick.IsChecked = picked.Contains(key);
        });

        var count = new TextBlock { Classes = { "count" } };
        Watch(field, () => count.Text = Lang.F("{0} из {1}", _values.Picked(field).Count(key => ticks.Any(item => item.Key == key)), ticks.Count));
        head.Children.Add(count);
        if (ticks.Count > 3)
        {
            Button Mini(string word, string tip, bool on)
            {
                // A button like the others of the page (the owner of Audion Get Tools, 11.10.2026: "ALL, NONE - must be buttons everywhere. Not just little blue words").
                var mini = new Button { Classes = { "small" }, Content = Lang.T(word), VerticalAlignment = VerticalAlignment.Center };
                ToolTip.SetTip(mini, Lang.T(tip));
                mini.Click += (_, _) => _values.Set(field, on ? string.Join(Values.ListSeparator, ticks.Select(item => item.Key)) : "");
                return mini;
            }
            head.Children.Add(Mini("ВСЕ", "Отметить все.", true));
            head.Children.Add(Mini("СНЯТЬ", "Снять все отметки.", false));
        }
        return block;
    }

    TextBox TextBox(Field field, int lines)
    {
        var box = new TextBox { PlaceholderText = field.Placeholder, Classes = { "masks" }, MinHeight = 24, Padding = new Thickness(8, 2), VerticalContentAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 4) };
        if (lines == 1) PixelGrid.Field(box);
        if (lines > 1)
        {
            box.AcceptsReturn = true;
            box.TextWrapping = TextWrapping.Wrap;
            box.MinHeight = 18 * lines;
            box.MaxHeight = 320;
        }
        Avalonia.Automation.AutomationProperties.SetAutomationId(box, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(box, field.Tip);
        box.TextChanged += (_, _) => _values.Set(field, box.Text ?? "");
        // The box a person types in is not rewritten under the cursor: only a value that came from elsewhere is put in.
        Watch(field, () => { if ((box.Text ?? "") != _values.Get(field)) box.Text = _values.Get(field); });
        return box;
    }

    /// <summary>The name of a choice, with the colour it stands for before it where the manifest gives one.</summary>
    static object Named(Option option)
    {
        if (option.Swatch.Length == 0 || !Color.TryParse(option.Swatch, out var colour)) return option.Name;
        return new StackPanel
        {
            Orientation = Orientation.Horizontal, Spacing = 6,
            Children =
            {
                new Border { Classes = { "swatch" }, Background = new SolidColorBrush(colour), VerticalAlignment = VerticalAlignment.Center },
                new TextBlock { Text = option.Name, VerticalAlignment = VerticalAlignment.Center },
            },
        };
    }

    /// <summary>The body of a block with the stripe of its group at its left: the mark the blocks of the former window had.</summary>
    static Control Striped(Control body, string group, bool documents)
    {
        var stripe = new Border { Classes = { "stripe", "g-" + (group.Length > 0 ? group : "parameters") } };
        stripe.Classes.Set("doc", documents);
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        grid.Children.Add(stripe);
        Grid.SetColumn(body, 1);
        grid.Children.Add(body);
        return grid;
    }

    /// <summary>
    /// A quality of a lossy format: the ready values of the manifest as switches, and a number of
    /// one's own beside them - one value, set either way. A switch is on while the number is its own.
    /// </summary>
    Control Quality(Field field)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal };
        var buttons = new List<(ToggleButton Button, string Key)>();
        foreach (var option in field.Options)
        {
            var key = option.Key;
            var button = new ToggleButton { Classes = { "switch" }, Content = key + "%", Margin = new Thickness(0, 0, 4, 4) };
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"field_{field.Id}_{key}");
            if (field.Tip.Length > 0) ToolTip.SetTip(button, field.Tip);
            button.Click += (_, _) =>
            {
                _values.Set(field, key);
                button.IsChecked = _values.Get(field) == key;
            };
            buttons.Add((button, key));
            row.Children.Add(button);
        }
        var box = NumberBox(field);
        box.Width = 64;
        box.Margin = new Thickness(buttons.Count > 0 ? 6 : 0, 0, 0, 4);
        row.Children.Add(box);
        row.Children.Add(new TextBlock { Classes = { "note" }, Text = "%", Margin = new Thickness(5, 0, 0, 4), VerticalAlignment = VerticalAlignment.Center });
        Watch(field, () =>
        {
            var current = _values.Get(field);
            foreach (var (button, key) in buttons) button.IsChecked = key == current;
        });
        return row;
    }

    /// <summary>
    /// A colour of one's own, as the classic has it (the owner, 14.10.2026: "sliders, fields, a colour patch"):
    /// the patch of the colour at the left, three rows of red, green and blue at its right - a slider and a
    /// field of 0-255 each. The value is "R,G,B", as the engine reads a colour.
    /// </summary>
    Control Rgb(Field field)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*,Auto"), RowDefinitions = new RowDefinitions("Auto,Auto,Auto"), MinWidth = 210, Margin = new Thickness(0, 0, 0, 4) };
        var patch = new Border { Classes = { "swatch", "patch" }, Width = 46, Height = double.NaN, Margin = new Thickness(0, 3, 10, 3), VerticalAlignment = VerticalAlignment.Stretch };
        Grid.SetRowSpan(patch, 3);
        grid.Children.Add(patch);
        var boxes = new List<TextBox>();
        var sliders = new List<Slider>();
        bool syncing = false;
        int[] Parts()
        {
            var parts = _values.Get(field).Split(',').Select(part => int.TryParse(part.Trim(), out var channel) ? Math.Clamp(channel, 0, 255) : 0).ToList();
            while (parts.Count < 3) parts.Add(0);
            return parts.Take(3).ToArray();
        }
        void Put(int index, int channel)
        {
            var parts = Parts();
            parts[index] = Math.Clamp(channel, 0, 255);
            _values.Set(field, string.Join(",", parts));
        }
        void Take(int index)
        {
            if (int.TryParse((boxes[index].Text ?? "").Trim(), out var channel)) Put(index, channel);
        }
        // A channel from none of it to all of it: black to the pure colour of the channel.
        foreach (var (letter, index, tone, pure) in new[] { ("R", 0, "#e5534b", "#ff0000"), ("G", 1, "#3fb950", "#00ff00"), ("B", 2, "#4a8fe7", "#0040ff") })
        {
            int at = index;
            var name = new TextBlock { Classes = { "note" }, Text = letter, Margin = new Thickness(0, 0, 6, 0), VerticalAlignment = VerticalAlignment.Center };
            Grid.SetRow(name, at);
            Grid.SetColumn(name, 1);
            grid.Children.Add(name);
            // The slider wears the colour of its channel: its filled part and its thumb.
            var slider = new Slider { Minimum = 0, Maximum = 255, SmallChange = 1, LargeChange = 16, IsSnapToTickEnabled = true, TickFrequency = 1, MinWidth = 72 };
            Avalonia.Automation.AutomationProperties.SetAutomationId(slider, $"field_{field.Id}_{letter.ToLowerInvariant()}_slider");
            if (field.Tip.Length > 0) ToolTip.SetTip(slider, field.Tip);
            slider.PropertyChanged += (_, e) =>
            {
                if (e.Property == RangeBase.ValueProperty && !syncing) Put(at, (int)Math.Round(slider.Value));
            };
            var chip = Chip(slider, new SolidColorBrush(Color.Parse(tone)), new[] { "#000000", pure });
            chip.Margin = new Thickness(0, 1, 8, 1);
            Grid.SetRow(chip, at);
            Grid.SetColumn(chip, 2);
            grid.Children.Add(chip);
            sliders.Add(slider);
            // Three digits at most: a narrow field, the minimal width of the theme set aside.
            var box = new TextBox { Width = 46, MinWidth = 0, Classes = { "masks" }, Height = 24, MinHeight = 24, Padding = new Thickness(6, 0), Margin = new Thickness(0, 1, 0, 1), VerticalContentAlignment = VerticalAlignment.Center };
            Avalonia.Automation.AutomationProperties.SetAutomationId(box, $"field_{field.Id}_{letter.ToLowerInvariant()}");
            if (field.Tip.Length > 0) ToolTip.SetTip(box, field.Tip);
            PixelGrid.Field(box);
            box.LostFocus += (_, _) => Take(at);
            box.KeyDown += (_, e) => { if (e.Key == Key.Enter) { Take(at); e.Handled = true; } };
            Grid.SetRow(box, at);
            Grid.SetColumn(box, 3);
            grid.Children.Add(box);
            boxes.Add(box);
        }
        Watch(field, () =>
        {
            var parts = Parts();
            syncing = true;
            for (int i = 0; i < 3; i++)
            {
                if (!boxes[i].IsFocused || (boxes[i].Text ?? "") != parts[i].ToString(CultureInfo.InvariantCulture)) boxes[i].Text = parts[i].ToString(CultureInfo.InvariantCulture);
                if (Math.Abs(sliders[i].Value - parts[i]) >= 0.5) sliders[i].Value = parts[i];
            }
            syncing = false;
            patch.Background = new SolidColorBrush(Color.FromRgb((byte)parts[0], (byte)parts[1], (byte)parts[2]));
        });
        return grid;
    }

    /// <summary>
    /// A number between two ends with a slider beside its field, as a colour of one's own has them: brightness,
    /// contrast, gamma, a tolerance. The slider wears the accent of the theme; the field takes a typed value.
    /// </summary>
    Control SliderBox(Field field)
    {
        double least = field.Min ?? 0, most = field.Max ?? 100, step = field.Step is { } given && given > 0 ? given : 1;
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), MinWidth = 220, Margin = new Thickness(0, 0, 0, 4) };
        var slider = new Slider { Minimum = least, Maximum = most, SmallChange = step, LargeChange = step * 10, TickFrequency = step, IsSnapToTickEnabled = true, MinWidth = 120 };
        IBrush? accent = Application.Current is { } app && app.TryFindResource("Quasar", app.ActualThemeVariant, out var found) ? found as IBrush : null;
        Avalonia.Automation.AutomationProperties.SetAutomationId(slider, $"field_{field.Id}_slider");
        if (field.Tip.Length > 0) ToolTip.SetTip(slider, field.Tip);
        bool syncing = false;
        slider.PropertyChanged += (_, e) =>
        {
            if (e.Property == RangeBase.ValueProperty && !syncing)
                _values.Set(field, Math.Round(slider.Value, 6).ToString("0.######", CultureInfo.InvariantCulture));
        };
        var chip = Chip(slider, accent, field.Track);
        chip.Margin = new Thickness(0, 0, 10, 0);
        grid.Children.Add(chip);
        var box = NumberBox(field);
        box.Width = 64;
        box.MinWidth = 0;
        box.Margin = new Thickness(0);
        Grid.SetColumn(box, 1);
        grid.Children.Add(box);
        Watch(field, () =>
        {
            if (!double.TryParse(_values.Get(field), NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) return;
            syncing = true;
            if (Math.Abs(slider.Value - number) > step / 2) slider.Value = number;
            syncing = false;
        });
        return grid;
    }

    /// <summary>
    /// A slider as the owner asked for it (14.10.2026: "smaller circles, and prettier - each in a dark chip with
    /// rounded corners"): a thumb of 12, a thin track, the slider in a chip as dark and as tall as a field beside it.
    /// The filled part and the thumb wear <paramref name="tone"/>: the accent of the theme, or the colour of a channel.
    /// </summary>
    static Border Chip(Slider slider, IBrush? tone, IReadOnlyList<string>? track = null)
    {
        // The air the theme leaves over and under a slider (15 and 15) would push it out of a chip as tall as a field.
        slider.Resources["SliderPreContentMargin"] = new GridLength(0);
        slider.Resources["SliderPostContentMargin"] = new GridLength(0);
        slider.Resources["SliderOutsideTickBarThemeHeight"] = 0.0;
        slider.Resources["SliderHorizontalHeight"] = 22.0;
        slider.Resources["SliderHorizontalThumbWidth"] = 12.0;
        slider.Resources["SliderHorizontalThumbHeight"] = 12.0;
        slider.Resources["SliderThumbCornerRadius"] = new CornerRadius(6);
        slider.Resources["SliderTrackThemeHeight"] = 3.0;
        LinearGradientBrush? drawn = null;
        if (track is { Count: >= 2 })
        {
            // The chip is the track: its colours from end to end, softened; the slider draws only its thumb.
            drawn = new LinearGradientBrush { StartPoint = new RelativePoint(0, 0.5, RelativeUnit.Relative), EndPoint = new RelativePoint(1, 0.5, RelativeUnit.Relative) };
            for (int at = 0; at < track.Count; at++)
            {
                var colour = Color.Parse(track[at]);
                drawn.GradientStops.Add(new GradientStop(colour, at / (double)(track.Count - 1)));
            }
            foreach (var key in new[] { "SliderTrackFill", "SliderTrackFillPointerOver", "SliderTrackFillPressed",
                                        "SliderTrackValueFill", "SliderTrackValueFillPointerOver", "SliderTrackValueFillPressed" })
                slider.Resources[key] = Brushes.Transparent;
            tone = new SolidColorBrush(Color.Parse("#f4f2ec"));
        }
        if (tone is not null)
        {
            if (drawn is null)
                foreach (var key in new[] { "SliderTrackValueFill", "SliderTrackValueFillPointerOver", "SliderTrackValueFillPressed" })
                    slider.Resources[key] = tone;
            foreach (var key in new[] { "SliderThumbBackground", "SliderThumbBackgroundPointerOver", "SliderThumbBackgroundPressed" })
                slider.Resources[key] = tone;
        }
        slider.Height = 22;
        slider.VerticalAlignment = VerticalAlignment.Center;
        slider.Margin = new Thickness(0);
        // A dark ring around the thumb (App.axaml, Slider.chip): it stays in sight at the white end of a strip.
        slider.Classes.Add("chip");
        var chip = new Border
        {
            CornerRadius = new CornerRadius(6), BorderThickness = new Thickness(1), Padding = new Thickness(8, 0),
            Height = 24, VerticalAlignment = VerticalAlignment.Center, Child = slider, ClipToBounds = true,
        };
        if (drawn is not null) chip.Background = drawn;
        else chip.Bind(Border.BackgroundProperty, chip.GetResourceObservable("InputBg"));
        chip.Bind(Border.BorderBrushProperty, chip.GetResourceObservable("BorderSoft"));
        // The thumb in the middle of the strip (the owner, 14.10.2026): where the template of the theme puts it is
        // measured once it is laid out, and the slider is moved by what is left - no number guessed by eye.
        void Centre(object? sender, EventArgs e)
        {
            if (slider.GetVisualDescendants().OfType<Thumb>().FirstOrDefault() is not { } thumb || thumb.Bounds.Height <= 0 || chip.Bounds.Height <= 0) return;
            if (thumb.TranslatePoint(new Point(0, thumb.Bounds.Height / 2), chip) is not { } middle) return;
            double off = (chip.Bounds.Height - chip.BorderThickness.Top - chip.BorderThickness.Bottom) / 2 + chip.BorderThickness.Top - middle.Y;
            if (Math.Abs(off) < 0.5) { slider.LayoutUpdated -= Centre; return; }
            slider.Margin = new Thickness(0, slider.Margin.Top + off, 0, slider.Margin.Bottom - off);
        }
        slider.LayoutUpdated += Centre;
        return chip;
    }

    /// <summary>A number: typed, or stepped with the arrow keys; kept inside min and max of the manifest.</summary>
    TextBox NumberBox(Field field)
    {
        var box = new TextBox { Width = 120, HorizontalAlignment = HorizontalAlignment.Left, Classes = { "masks" }, Height = 24, MinHeight = 24, Padding = new Thickness(8, 0), VerticalContentAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 4) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(box, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(box, field.Tip);
        PixelGrid.Field(box);
        double step = field.Step is { } given && given > 0 ? given : 1;
        string Fit(double number)
        {
            if (field.Min is { } min && number < min) number = min;
            if (field.Max is { } max && number > max) number = max;
            return number.ToString("0.######", CultureInfo.InvariantCulture);
        }
        void Take()
        {
            var typed = (box.Text ?? "").Trim().Replace(',', '.');
            if (double.TryParse(typed, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) _values.Set(field, Fit(number));
            box.Text = _values.Get(field);
        }
        void Move(int direction)
        {
            if (!double.TryParse(_values.Get(field), NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) number = 0;
            _values.Set(field, Fit(Math.Round(number + direction * step, 6)));
        }
        box.LostFocus += (_, _) => Take();
        box.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { Take(); e.Handled = true; }
            else if (e.Key == Key.Up) { Take(); Move(1); e.Handled = true; }
            else if (e.Key == Key.Down) { Take(); Move(-1); e.Handled = true; }
        };
        Watch(field, () => { if (!box.IsFocused || (box.Text ?? "") != _values.Get(field)) box.Text = _values.Get(field); });
        return box;
    }
}
