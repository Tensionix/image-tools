using System.Collections.Generic;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Threading;
using AudionImageTools.Core;
using AudionImageTools.Views;
using Page = AudionImageTools.Core.Page;

namespace AudionImageTools;

/// <summary>
/// The pages of the window. A page is built when it is first opened and then stays in the window,
/// hidden while another is in sight: to put a hundred cards into the window takes a quarter of a
/// second and to take them out as long (measured 10.10.2026), to show what is already there takes
/// nothing. A page whose form has to change - a field its shape depends on was set, the theme
/// changed - is built again when it is next in sight, not before.
/// </summary>
public partial class MainWindow
{
    sealed class PageView
    {
        public required Page Page;
        public required Form Form;
        public required ScrollViewer Root;
        public required StackPanel Cards;
        /// <summary>The buttons of the page that run something.</summary>
        public readonly List<Button> RunButtons = new();
        /// <summary>A page with one form keeps its name, its buttons and "back to the defaults" in the bar over the cards.</summary>
        public bool HasBar;
        public string BarTitle = "";
        public readonly List<Button> BarButtons = new();
        public List<Field> ResetFields = new();
        /// <summary>The page is to be built before it is shown: never built yet, or what it shows is out of date.</summary>
        public bool Stale = true;
    }

    readonly Dictionary<string, PageView> _views = new();
    PageView? _view;

    static string KeyOf(Page page) => ValueStore.KeyOf(page);

    PageView ViewOf(Page page)
    {
        if (_views.TryGetValue(KeyOf(page), out var known)) return known;
        var cards = new StackPanel { Margin = new Thickness(10, 10, 10, 4), Spacing = 8 };
        var root = new ScrollViewer
        {
            Content = cards, IsVisible = false,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        };
        PageView? view = null;
        var form = new Form(_store.Of(page), () => Outdated(view!)) { Grown = CentreWords, Documents = page.Row == "documents" };
        view = new PageView { Page = page, Form = form, Root = root, Cards = cards };
        PageHost.Children.Add(root);
        return _views[KeyOf(page)] = view;
    }

    /// <summary>The form of a page has to change. The page in sight is built again at once; a hidden one, when it is next opened.</summary>
    void Outdated(PageView view)
    {
        view.Stale = true;
        if (ReferenceEquals(view, _view)) RebuildSoon();
    }

    void SelectPage(Page page)
    {
        _page = page;
        if (page.Section is { } section) _lastPage[section.Id] = page.Id;
        foreach (var child in PageRow.Children)
            if (child is ToggleButton tab) tab.IsChecked = (string?)tab.Tag == page.Id;
        var view = ViewOf(page);
        _view = view;
        // The values of the page: its fields are known before a condition reads them (Core\Values.cs, ValueStore.Open).
        _store.Open(page);
        if (view.Stale) Build(view, whole: false);
        Show(view);
        ShowPreview(page);
    }

    /// <summary>The page comes into sight: the others hide, the bar over the cards takes its name and its buttons.</summary>
    void Show(PageView view)
    {
        CardsNote.IsVisible = false;
        foreach (var other in _views.Values) other.Root.IsVisible = ReferenceEquals(other, view);
        ActionButtons.Children.Clear();
        foreach (var button in view.BarButtons) ActionButtons.Children.Add(button);
        ActionTitle.Text = view.BarTitle;
        ActionTitle.Classes.Set("doc", view.Page.Row == "documents");
        ActionReset.IsVisible = view.ResetFields.Count > 0;
        ActionBar.IsVisible = view.HasBar;
        PageBar.IsVisible = PageRow.IsVisible;
        ApplyBusy();
        CentreWords();
    }

    bool _rebuildPosted;

    /// <summary>The page in sight is built again after the press that asked for it has been handled, once for any number of changes.</summary>
    void RebuildSoon()
    {
        if (_rebuildPosted) return;
        _rebuildPosted = true;
        Dispatcher.UIThread.Post(() =>
        {
            _rebuildPosted = false;
            if (_view is not { } view) return;
            var offset = view.Root.Offset;
            // Built again in place: whole at once when the person has scrolled, so the place he was at is still there.
            Build(view, whole: offset.Y >= 1);
            Show(view);
            Dispatcher.UIThread.Post(() => view.Root.Offset = offset, DispatcherPriority.Loaded);
        });
    }

    /// <summary>"Back to the defaults": the fields of the page go back to the values of the program, and the page is built again.</summary>
    void ResetFields(PageView view, List<Field> fields)
    {
        _store.Of(view.Page).Reset(fields);
        Outdated(view);
    }

    /// <summary>Every page is out of date: the theme or a font changed. The one in sight is built again now.</summary>
    void OutdateAll()
    {
        foreach (var view in _views.Values) view.Stale = true;
        if (_view is not null) RebuildSoon();
    }

    /// <summary>Every page is thrown away: the language changed, and with it every word a page was built of.</summary>
    void ForgetPages()
    {
        foreach (var view in _views.Values) view.Form.Detach();
        _views.Clear();
        _view = null;
        PageHost.Children.Clear();
        ActionButtons.Children.Clear();
    }

    // ------------------------------------------------------------ the cards of a page

    void Build(PageView view, bool whole)
    {
        var page = view.Page;
        view.Form.Forget();
        view.Form.Lazy = !whole;
        view.Cards.Children.Clear();
        view.RunButtons.Clear();
        view.BarButtons.Clear();
        view.ResetFields = new List<Field>();
        view.HasBar = false;
        view.BarTitle = "";

        // A page with one form: its buttons stand over the form and stay in sight while it scrolls.
        // An operation that is not a button of a block is a form, with fields or without ("Split TIFF" asks for nothing).
        var forms = page.Cards().Where(card => !card.Host.Direct || card.Guests.Count > 0).ToList();
        var alone = forms.Count == 1 ? forms[0].Host : null;

        // An operation with a form is a card of its own; operations that need nothing but a
        // press stand together in the block the layout names, button beside button.
        var blocks = new Dictionary<string, WrapPanel>();
        foreach (var (host, guests) in page.Cards())
        {
            if (!host.Direct || guests.Count > 0) { view.Cards.Children.Add(Card(view, host, guests, ReferenceEquals(host, alone))); continue; }
            var name = host.BlockName.Length > 0 ? host.BlockName : page.Name;
            if (!blocks.TryGetValue(name, out var row))
            {
                blocks[name] = row = new WrapPanel { Orientation = Orientation.Horizontal };
                view.Cards.Children.Add(new Border
                {
                    Classes = { "card" }, Padding = new Thickness(10, 8, 8, 4),
                    Child = new StackPanel { Children = { new TextBlock { Classes = { "blockname" }, Text = name, Margin = new Thickness(0, 0, 0, 8) }, row } },
                });
            }
            row.Children.Add(RunButton(view, host, inBlock: true));
        }
        if (view.Form.Unknown.Count > 0)
        {
            AppendLines(new[] { Lang.F("[GUI] поля неизвестного вида не показаны: {0}", string.Join("; ", view.Form.Unknown)) });
            view.Form.Unknown.Clear();
        }
        if (Lang.Code != "ru") Lang.Walk(view.Cards);
        view.Stale = false;
        view.Form.Lazy = true;
    }

    /// <summary>
    /// Every word of a button, a chip and a badge to the vertical middle of its control, on whole
    /// pixels (Views\PixelGrid.cs): asked once the part just built is in the window.
    /// </summary>
    void CentreWords() => Dispatcher.UIThread.Post(() => PixelGrid.Adopt(this), DispatcherPriority.Loaded);

    /// <summary>
    /// The card of an operation with fields: its name, its buttons - the operations the layout
    /// places beside it, then its own - and "back to the defaults" on one line, the form under
    /// them. The one form of its page hands that line to the bar over the cards.
    /// </summary>
    Control Card(PageView view, Node host, List<Node> guests, bool alone)
    {
        var fields = host.Fields.ToList();
        var name = host.BlockName.Length > 0 ? host.BlockName : view.Page.Name;
        var buttons = new List<Button>();
        foreach (var node in guests.Append(host))
        {
            // A button may be in sight only for some values of the form.
            if (node.VisibleWhen is { } condition)
            {
                view.Form.Shapes(condition.Keys);
                if (!view.Form.InSight(condition)) continue;
            }
            buttons.Add(RunButton(view, node, inBlock: false));
        }
        // The filled one - the main action - stands last, at the right edge, the others before it.
        buttons = buttons.OrderBy(button => button.Classes.Contains("fill") ? 1 : 0).ToList();
        var form = host.Fields.Count > 0 ? view.Form.Build(host) : null;

        if (alone)
        {
            view.HasBar = true;
            view.BarTitle = Upper(name);
            view.BarButtons.AddRange(buttons);
            view.ResetFields = fields;
            // A form without a field says what its run does, where the fields would stand.
            return form ?? new TextBlock { Classes = { "note" }, Text = host.About, TextWrapping = Avalonia.Media.TextWrapping.Wrap, Margin = new Thickness(14, 12) };
        }

        var reset = new Button { Classes = { "tool" }, Content = Icons.Sign("undo-2"), Margin = new Thickness(6, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        ToolTip.SetTip(reset, Lang.T("К умолчаниям: вернуть поля этой карточки к значениям программы."));
        reset.Click += (_, _) => ResetFields(view, fields);
        reset.IsVisible = fields.Count > 0;
        var row = new WrapPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center };
        foreach (var button in buttons) row.Children.Add(button);
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Margin = new Thickness(0, 0, 0, form is null ? 0 : 7) };
        head.Children.Add(new TextBlock { Classes = { "blockname" }, Text = name });
        Grid.SetColumn(row, 1);
        head.Children.Add(row);
        Grid.SetColumn(reset, 2);
        head.Children.Add(reset);
        var body = new StackPanel { Children = { head } };
        if (form is not null) body.Children.Add(form);
        return new Border { Classes = { "card" }, Padding = new Thickness(10, 8, 8, 6), Child = body };
    }

    /// <summary>
    /// The button that runs an operation: its sign and its name, nothing more - what it does is
    /// in its tooltip (the owner, 10.10.2026: a line of description stands on the sections alone).
    /// The main action of a card is filled with the accent; what removes - with Burn Orange.
    /// </summary>
    Button RunButton(PageView view, Node node, bool inBlock)
    {
        var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center };
        // The run of a form says RUN: the name of the operation stands at the left of the same bar. No sign on it.
        bool runs = node.Tone == "run" && !inBlock;
        if (!runs && Icons.Glyph(node.Icon) is not null) face.Children.Add(Icons.Sign(node.Icon));
        face.Children.Add(new TextBlock { Text = runs ? Upper(Lang.T("Запустить")) : Upper(node.Name) });
        var button = new Button
        {
            Tag = node, Classes = { "step" }, Content = face, Height = 30, MinHeight = 30,
            Margin = inBlock ? new Thickness(0, 0, 4, 4) : new Thickness(4, 0, 0, 0),
        };
        button.Classes.Set("fill", node.Tone is "run" or "burn" || node.Primary);
        button.Classes.Set("burn", node.Tone == "burn");
        button.Classes.Set("quiet", node.Tone == "quick");
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, "run_" + node.Id);
        ToolTip.SetTip(button, TipOf(node));
        button.Click += (_, _) => Press(node);
        view.RunButtons.Add(button);
        return button;
    }
}
