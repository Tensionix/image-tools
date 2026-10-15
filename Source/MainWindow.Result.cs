using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using AudionImageTools.Core;

namespace AudionImageTools;

/// <summary>
/// The panel RESULT: what the last check of documents found - "Check DPI" or "Raise to DPI". The
/// engine leaves summary.json in the folder of its report (system_core\documents\commands.py): the
/// numbers, which the window says in its own language, and the table it wrote. The panel stays until
/// the next check or until it is closed; any other operation leaves it as it is.
/// </summary>
public partial class MainWindow
{
    string _resultReport = "", _resultFolder = "";

    /// <summary>Rows of a table shown at most: a document of hundreds of pictures is read in its report.</summary>
    const int ResultRows = 300;

    void WireResult()
    {
        ResultReportButton.Click += (_, _) => OpenFile(_resultReport);
        ResultFolderButton.Click += (_, _) => { if (_resultFolder.Length > 0) OpenFolder(_resultFolder); };
        ResultCloseButton.Click += (_, _) => ResultCard.IsVisible = false;
    }

    void OpenFile(string file)
    {
        if (file.Length == 0 || !File.Exists(file)) { SetStatus("Отчёта нет на диске."); return; }
        try { Process.Start(new ProcessStartInfo(file) { UseShellExecute = true }); }
        catch (Exception ex) { SetStatus(Lang.F("Файл не открылся: {0}", ex.Message)); }
    }

    /// <summary>The folder of the report of the run that has just ended, as the console command wrote it into result.json; "" - none.</summary>
    static string ReportOfLastRun()
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Door.ResultFile, Encoding.UTF8));
            return doc.RootElement.TryGetProperty("data", out var data) && data.ValueKind == JsonValueKind.Object
                   && data.TryGetProperty("report", out var report) && report.ValueKind == JsonValueKind.String ? report.GetString() ?? "" : "";
        }
        catch { return ""; }
    }

    void ShowResult()
    {
        var folder = ReportOfLastRun();
        var file = folder.Length > 0 ? Path.Combine(folder, "summary.json") : "";
        if (file.Length == 0 || !File.Exists(file)) return;
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(file, Encoding.UTF8));
            var root = doc.RootElement;
            int Number(string name) => root.TryGetProperty(name, out var value) && value.TryGetInt32(out var number) ? number : 0;
            string Text(string name) => root.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
            var kind = Text("kind");
            int threshold = Number("threshold");
            ResultTable.Children.Clear();
            ResultTable.RowDefinitions.Clear();
            ResultTable.ColumnDefinitions.Clear();
            // The name of the run; a table of one document adds the name of the document to it.
            ResultTitle.Text = _runName;
            if (kind == "dpi_check")
            {
                var said = Lang.F("{0} из {1} вставок ниже {2} ppi", Number("below"), Number("measured"), threshold);
                if (Number("unmeasured") > 0) said += "; " + Lang.F("не измерено: {0} (названы в таблице)", Number("unmeasured"));
                if (Number("refused") > 0) said += "; " + Lang.F("не прочитано документов: {0} - причина в журнале", Number("refused"));
                ResultSummary.Text = said;
                ResultSummary.Classes.Set("good", Number("below") == 0 && Number("unmeasured") == 0);
                FillCheckTable(Path.Combine(folder, Text("table")), threshold);
            }
            else if (kind is "dpi_raise" or "pdf_shrink" or "pdf_watermark" or "pdf_rotate" or "pdf_merge" or "pdf_split" or "pdf_clean_meta")
            {
                int done = Number("done"), documents = Number("documents");
                ResultSummary.Text = Lang.F("Готовы и проверены документов: {0} из {1}", done, documents) + " · " + Paths.Short(Text("target"));
                ResultSummary.Classes.Set("good", done == documents);
                FillRaiseTable(root, kind);
            }
            else return;
            _resultReport = Path.Combine(folder, Text("report"));
            _resultFolder = folder;
            ResultCard.IsVisible = true;
            if (Lang.Code != "ru") Lang.Walk(ResultCard);
            CentreWords();
        }
        catch (Exception ex)
        {
            AppendLines(new[] { "[GUI] " + Lang.F("итог проверки не прочитан: {0}", ex.Message) });
        }
    }

    /// <summary>A table of the panel: its heads, then its rows; a cell may wear a tone and say more in its tooltip.</summary>
    void Table(IReadOnlyList<string> heads, IEnumerable<(string[] Cells, string Tone, string Tip)> rows, int total)
    {
        for (int column = 0; column < heads.Count; column++) ResultTable.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        void Add(int row, int column, string text, params string[] classes)
        {
            var cell = new TextBlock { Text = text, Margin = new Thickness(0, 1, 12, 1), VerticalAlignment = VerticalAlignment.Center };
            foreach (var name in classes) cell.Classes.Add(name);
            Grid.SetRow(cell, row);
            Grid.SetColumn(cell, column);
            ResultTable.Children.Add(cell);
        }
        ResultTable.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        for (int column = 0; column < heads.Count; column++) Add(0, column, heads[column], "factname");
        // The heads stay over the rows they name: the names of the columns in the small type of the facts.
        int at = 1;
        foreach (var (cells, tone, tip) in rows.Take(ResultRows))
        {
            ResultTable.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            for (int column = 0; column < cells.Length && column < heads.Count; column++)
            {
                var classes = new List<string> { "cell" };
                if (tone.Length > 0) classes.Add(tone);
                Add(at, column, cells[column], classes.ToArray());
                if (tip.Length > 0) ToolTip.SetTip(ResultTable.Children[^1], tip);
            }
            at++;
        }
        if (total > ResultRows)
        {
            ResultTable.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            var more = new TextBlock { Classes = { "note" }, Text = Lang.F("показаны первые {0} строк из {1}; все - в отчёте", ResultRows, total), Margin = new Thickness(0, 4, 0, 0) };
            Grid.SetRow(more, at);
            Grid.SetColumnSpan(more, heads.Count);
            ResultTable.Children.Add(more);
        }
        ResultScroll.IsVisible = total > 0;
    }

    /// <summary>
    /// The table of "Check DPI": a line for every placement - the document, the place, the pixels, the
    /// size, the resolution, the density stated; a placement below the threshold in Burn Orange, one not
    /// measured in amber, its reason in the tooltip.
    /// </summary>
    void FillCheckTable(string csv, int threshold)
    {
        if (!File.Exists(csv)) { ResultScroll.IsVisible = false; return; }
        // document;place;picture;pixels;placed, mm;ppi;states, dpi;stored;note - written by the engine.
        var lines = File.ReadAllLines(csv, new UTF8Encoding(true)).Skip(1).Where(line => line.Length > 0).Select(SplitCsv).Where(parts => parts.Count >= 9).ToList();
        // One document: its name goes into the head of the panel, and the resolution stands second, in sight in a narrow column.
        var documents = lines.Select(parts => parts[0]).Distinct().ToList();
        bool one = documents.Count == 1;
        if (one) ResultTitle.Text = _runName + " · " + documents[0];
        var rows = new List<(string[] Cells, string Tone, string Tip)>();
        foreach (var parts in lines)
        {
            string tone = int.TryParse(parts[5], out var ppi) ? (ppi < threshold ? "bad" : "") : "warn";
            var tip = parts[2] + (parts[7].Length > 0 ? " · " + parts[7] : "") + (parts[8].Length > 0 ? "\n" + parts[8] : "");
            var cells = new List<string> { parts[1], parts[5], parts[6], parts[3], parts[4] };
            if (!one) cells.Add(parts[0]);
            rows.Add((cells.ToArray(), tone, tip));
        }
        var heads = new List<string> { Lang.T("Место"), "ppi", Lang.T("Метка, dpi"), Lang.T("Пиксели"), Lang.T("Вставка, мм") };
        if (!one) heads.Add(Lang.T("Документ"));
        Table(heads, rows, rows.Count);
    }

    /// <summary>The table of a copy of documents - "Raise to DPI", the operations of PDF over documents and pages: a line for every
    /// document - done, partial, refused or failed, and what it came to.</summary>
    void FillRaiseTable(JsonElement root, string kind)
    {
        var rows = new List<(string[] Cells, string Tone, string Tip)>();
        if (root.TryGetProperty("rows", out var list) && list.ValueKind == JsonValueKind.Array)
            foreach (var row in list.EnumerateArray())
            {
                var cells = row.EnumerateArray().Where(cell => cell.ValueKind == JsonValueKind.String).Select(cell => cell.GetString() ?? "").ToArray();
                if (cells.Length < 3) continue;
                // A document done by an operation over pages: what it came to, said from its numbers in the language of the window.
                var facts = row.EnumerateArray().FirstOrDefault(cell => cell.ValueKind == JsonValueKind.Object);
                if (cells[1] == "done" && facts.ValueKind == JsonValueKind.Object && Facts(kind, facts) is { Length: > 0 } said) cells[2] = said;
                var (word, tone) = cells[1] switch
                {
                    "done" => (Lang.T("готово"), "good"),
                    "partial" => (Lang.T("частично"), "warn"),
                    "refused" => (Lang.T("отказ"), "bad"),
                    _ => (Lang.T("ошибка"), "bad"),
                };
                rows.Add((new[] { cells[0], word, cells[2] }, tone, cells[2]));
            }
        // What each document came to - the weight before and after, the reason of a refusal - when any says something.
        var heads = rows.Any(row => row.Cells[2].Length > 0)
            ? new[] { Lang.T("Документ"), Lang.T("Итог"), Lang.T("Подробно") }
            : new[] { Lang.T("Документ"), Lang.T("Итог") };
        Table(heads, rows, rows.Count);
    }

    /// <summary>What a document done by an operation over pages came to, from the numbers the engine left; "" - nothing to say.</summary>
    static string Facts(string kind, JsonElement facts)
    {
        int Number(string name) => facts.TryGetProperty(name, out var value) && value.TryGetInt32(out var number) ? number : 0;
        switch (kind)
        {
            case "pdf_rotate":
                return Lang.F("повёрнуто страниц: {0}", Number("turned"));
            case "pdf_split":
                return Lang.F("файлов: {0}", Number("files"));
            case "pdf_merge":
                var said = Lang.F("документов: {0}, страниц: {1}, в порядке имён", Number("documents"), Number("pages"));
                return Number("bookmarks") > 0 ? said + "; " + Lang.F("закладки не перенесены из документов: {0}", Number("bookmarks")) : said;
            case "pdf_clean_meta":
                var taken = facts.TryGetProperty("taken", out var list) && list.ValueKind == JsonValueKind.Array
                    ? list.EnumerateArray().Select(item => item.GetString() ?? "").Where(item => item.Length > 0).ToList() : new List<string>();
                return taken.Count > 0 ? Lang.F("убрано: {0}", string.Join(", ", taken)) : Lang.T("свойств в документе не было");
            default:
                return "";
        }
    }

    /// <summary>A line of a CSV the engine wrote (`;`, cells quoted when they hold one).</summary>
    static List<string> SplitCsv(string line)
    {
        var cells = new List<string>();
        var cell = new StringBuilder();
        bool quoted = false;
        for (int i = 0; i < line.Length; i++)
        {
            char ch = line[i];
            if (quoted)
            {
                if (ch == '"' && i + 1 < line.Length && line[i + 1] == '"') { cell.Append('"'); i++; }
                else if (ch == '"') quoted = false;
                else cell.Append(ch);
            }
            else if (ch == '"') quoted = true;
            else if (ch == ';') { cells.Add(cell.ToString()); cell.Clear(); }
            else cell.Append(ch);
        }
        cells.Add(cell.ToString());
        return cells;
    }
}
