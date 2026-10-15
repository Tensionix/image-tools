using System;
using System.Collections.Generic;
using System.Linq;
using Avalonia;
using Avalonia.Controls;

namespace AudionImageTools.Views;

/// <summary>
/// A row of switches that share its width equally - until a name does not fit its share: that
/// switch takes the width of its name, and the others share what is left. A band of four pages
/// stands as the sections over it do; a fifth page must not cut the name of its neighbour.
///
/// <see cref="Break"/> parts two groups of the row - the pages over pictures and the pages over
/// documents: a gap of <see cref="GroupGap"/> stands between them while the row holds both, and when
/// the names of both do not fit one line, the second group goes to a line of its own under the first;
/// a group too long for a line wraps into more lines (the plan of the window: the band wraps, it
/// never cuts a name).
/// </summary>
public sealed class EvenRow : Panel
{
    public static readonly StyledProperty<double> SpacingProperty = AvaloniaProperty.Register<EvenRow, double>(nameof(Spacing));
    public static readonly StyledProperty<int> BreakProperty = AvaloniaProperty.Register<EvenRow, int>(nameof(Break), -1);

    static EvenRow()
    {
        AffectsMeasure<EvenRow>(SpacingProperty, BreakProperty);
    }

    public double Spacing
    {
        get => GetValue(SpacingProperty);
        set => SetValue(SpacingProperty, value);
    }

    /// <summary>The index of the first child of the second group; -1 - the row is one group.</summary>
    public int Break
    {
        get => GetValue(BreakProperty);
        set => SetValue(BreakProperty, value);
    }

    /// <summary>The gap between the two groups on one line: wider than the spacing, so the groups read apart.</summary>
    public double GroupGap { get; set; } = 14;

    /// <summary>The row stands on more than one line: the names did not fit one.</summary>
    public bool Wrapped { get; private set; }

    int BreakAmong(List<Control> shown)
    {
        if (Break <= 0 || Break >= Children.Count) return -1;
        int at = shown.IndexOf(Children[Break]);
        return at > 0 && at < shown.Count ? at : -1;
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        var shown = Children.Where(child => child.IsVisible).ToList();
        foreach (var child in shown) child.Measure(new Size(double.PositiveInfinity, availableSize.Height));
        _lines = Lines(shown, availableSize.Width);
        Wrapped = _lines.Count > 1;
        if (_lines.Count == 0) return new Size(0, 0);
        double wanted = _lines.Count == 1 ? LineWidth(_lines[0].Items) + _lines[0].Gap : _lines.Max(line => LineWidth(line.Items));
        double height = _lines.Sum(line => Tall(line.Items)) + Spacing * Math.Max(0, _lines.Count - 1);
        return new Size(double.IsInfinity(availableSize.Width) ? wanted : availableSize.Width, height);
    }

    /// <summary>The lines of the row, as measured: their switches and, for the one line of both groups, the gap before the second.</summary>
    List<(List<Control> Items, int GapAt, double Gap)> _lines = new();

    double LineWidth(IReadOnlyCollection<Control> line) => line.Sum(child => child.DesiredSize.Width) + Spacing * Math.Max(0, line.Count - 1);

    static double Tall(IEnumerable<Control> line) => line.Select(child => child.DesiredSize.Height).DefaultIfEmpty(0).Max();

    /// <summary>
    /// Both groups on one line when their names fit it, the gap between them; else each group on lines of its own,
    /// a group broken into as many lines as its names need - a name is never cut.
    /// </summary>
    List<(List<Control> Items, int GapAt, double Gap)> Lines(List<Control> shown, double width)
    {
        var lines = new List<(List<Control> Items, int GapAt, double Gap)>();
        if (shown.Count == 0) return lines;
        int at = BreakAmong(shown);
        double gap = at > 0 ? GroupGap - Spacing : 0;
        if (double.IsInfinity(width) || LineWidth(shown) + gap <= width)
        {
            lines.Add((shown, at, gap));
            return lines;
        }
        foreach (var group in at > 0 ? new[] { shown.Take(at).ToList(), shown.Skip(at).ToList() } : new[] { shown })
        {
            var greedy = new List<List<Control>>();
            var line = new List<Control>();
            foreach (var child in group)
            {
                if (line.Count > 0 && LineWidth(line) + Spacing + child.DesiredSize.Width > width)
                {
                    greedy.Add(line);
                    line = new List<Control>();
                }
                line.Add(child);
            }
            if (line.Count > 0) greedy.Add(line);
            foreach (var one in Even(group, greedy.Count, width) ?? greedy) lines.Add((one, -1, 0));
        }
        return lines;
    }

    /// <summary>
    /// The same number of lines with the switches shared between them evenly - three and three, not five and a
    /// lone one stretched over the whole width; null when an even line would not fit and the lines stay as filled.
    /// </summary>
    List<List<Control>>? Even(List<Control> group, int count, double width)
    {
        if (count < 2) return null;
        var lines = new List<List<Control>>();
        int at = 0;
        for (int index = 0; index < count; index++)
        {
            int take = (group.Count - at + (count - index) - 1) / (count - index);
            var line = group.Skip(at).Take(take).ToList();
            if (LineWidth(line) > width) return null;
            lines.Add(line);
            at += take;
        }
        return lines;
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        double top = 0;
        foreach (var (items, gapAt, gap) in _lines)
        {
            double tall = Tall(items);
            var widths = Shares(items.Select(child => child.DesiredSize.Width).ToArray(), finalSize.Width - Spacing * (items.Count - 1) - gap);
            double left = 0;
            for (int i = 0; i < items.Count; i++)
            {
                if (i == gapAt) left += gap;
                items[i].Arrange(new Rect(left, top, widths[i], _lines.Count == 1 ? finalSize.Height : tall));
                left += widths[i] + Spacing;
            }
            top += tall + Spacing;
        }
        return finalSize;
    }

    /// <summary>
    /// Equal shares of the room; whoever wants more than a share is given what it wants, and the
    /// rest share what is left - again and again, until every share fits its owner.
    /// </summary>
    public static double[] Shares(double[] wants, double room)
    {
        var widths = new double[wants.Length];
        var settled = new bool[wants.Length];
        while (true)
        {
            int free = settled.Count(one => !one);
            if (free == 0) break;
            double share = Math.Max(0, (room - Enumerable.Range(0, wants.Length).Where(i => settled[i]).Sum(i => widths[i])) / free);
            bool grew = false;
            for (int i = 0; i < wants.Length; i++)
                if (!settled[i] && wants[i] > share) { settled[i] = true; widths[i] = wants[i]; grew = true; }
            if (grew) continue;
            for (int i = 0; i < wants.Length; i++)
                if (!settled[i]) widths[i] = share;
            break;
        }
        return widths;
    }
}
