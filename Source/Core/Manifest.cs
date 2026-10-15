using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AudionImageTools.Core;

/// <summary>
/// What the door tells of the program (image_cli.cmd describe): the sections of the window, their
/// pages, the operations of every page with their fields. The window draws by it and knows no
/// section and no operation by its name: what stands where is config\window_layout.yaml, what an
/// operation is - config\tool_manifest.yaml.
/// </summary>
public sealed class Described
{
    public string Version { get; set; } = "";
    public ProjectPaths Paths { get; set; } = new();
    public Layout Layout { get; set; } = new();
    /// <summary>What the engine can do on this machine: the badges of the header (system_core\core\abilities.py).</summary>
    public List<Ability> Abilities { get; set; } = new();

    static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
    };

    /// <summary>The answer of "describe" read; an answer that is no description throws.</summary>
    public static Described Parse(string json)
    {
        var told = JsonSerializer.Deserialize<Described>(json, Json) ?? throw new JsonException("the door gave no description");
        foreach (var section in told.Layout.Sections)
            foreach (var page in section.Pages)
            {
                page.Section = section;
                foreach (var node in page.Operations) node.Page = page;
            }
        return told;
    }

    /// <summary>Everything that has a button: the operations of the pages, then those of the header, then those beside the paths.</summary>
    public IEnumerable<Node> Operations() =>
        Layout.Sections.SelectMany(section => section.Pages).SelectMany(page => page.Operations).Concat(Layout.Service).Concat(Layout.Folders);
}

/// <summary>A badge of the header: a few words, whether the engine can, and what stands behind it.</summary>
public sealed class Ability
{
    public string Id { get; set; } = "";
    public string Text { get; set; } = "";
    public bool Ok { get; set; }
    public string Tip { get; set; } = "";
    public string TipRu { get; set; } = "";

    [JsonIgnore] public string Says => Words.Pick(TipRu, Tip);
}

/// <summary>The folders of the project, as the door resolves them.</summary>
public sealed class ProjectPaths
{
    public string Root { get; set; } = "";
    public string Input { get; set; } = "";
    public string Output { get; set; } = "";
    public string Logs { get; set; } = "";
    public string Report { get; set; } = "";
    public string Config { get; set; } = "";
}

public sealed class Layout
{
    public List<Section> Sections { get; set; } = new();
    /// <summary>The operations of the program itself: the small buttons of the header.</summary>
    public List<Node> Service { get; set; } = new();
    /// <summary>
    /// The operations of the working folders of the program: buttons beside the paths.
    /// They run on `input` and `output` of the program itself - no source and no target is named
    /// to the door - and the question before one names both folders.
    /// </summary>
    public List<Node> Folders { get; set; } = new();
    /// <summary>The fields whose value is one for the whole window; every other field belongs to its page.</summary>
    public List<string> Shared { get; set; } = new();
}

/// <summary>A section of the window: a large button of the row under the header.</summary>
public sealed class Section
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Icon { get; set; } = "";
    public string About { get; set; } = "";
    public string AboutRu { get; set; } = "";
    public List<Page> Pages { get; set; } = new();

    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string Line => Words.Pick(AboutRu, About);
}

/// <summary>A page of a section: one of the row under the sections, with its cards.</summary>
public sealed class Page
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Icon { get; set; } = "";
    public string About { get; set; } = "";
    public string AboutRu { get; set; } = "";
    /// <summary>The operations of the page read a folder the person may choose: the page shows the row SOURCE, and the door is told the folder.</summary>
    public bool Source { get; set; }
    /// <summary>The row of the section the page stands in: "images" - pictures, "documents" - the pictures inside DOCX, PPTX and PDF.</summary>
    public string Row { get; set; } = "";
    /// <summary>The page shows what its operation makes of one picture before it is run (the layout says so; MainWindow.Preview.cs).</summary>
    public bool Preview { get; set; }
    /// <summary>The documents an operation over documents takes - docx, pptx, pdf (the layout says them): their marks stand on its button.</summary>
    public List<string> Formats { get; set; } = new();
    public List<Node> Operations { get; set; } = new();

    [JsonIgnore] public Section? Section { get; set; }
    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string Line => Words.Pick(AboutRu, About);

    /// <summary>
    /// The operations of the page as its cards: an operation with a form is a card, and the
    /// operations the layout places beside it stand in that card as buttons that read the same
    /// fields.
    /// </summary>
    public List<(Node Host, List<Node> Guests)> Cards() =>
        Operations.Where(node => node.Beside.Length == 0)
            .Select(host => (host, Operations.Where(guest => guest.Beside == host.Id).ToList())).ToList();
}

/// <summary>An operation as it stands on a page: what a button runs.</summary>
public sealed class Node
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Description { get; set; } = "";
    public string DescriptionRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    /// <summary>"safe" or "dangerous": a dangerous one is asked about.</summary>
    public string Kind { get; set; } = "";
    public string Icon { get; set; } = "";
    /// <summary>What its button wears: "run" - the main action of a card, "burn" - it removes; "" - a plain one.</summary>
    public string Tone { get; set; } = "";
    /// <summary>The logical block of its page an operation without a form stands in.</summary>
    public string Block { get; set; } = "";
    public string BlockRu { get; set; } = "";
    /// <summary>The blocks of the form in the order the layout wants them (`groups` of the card); empty - as the fields come.</summary>
    public List<string> Groups { get; set; } = new();
    /// <summary>The operation whose card this one shares; "" - a card of its own.</summary>
    public string Beside { get; set; } = "";
    public bool Runs { get; set; }
    /// <summary>Runs and has no field to draw: a button is all it needs.</summary>
    public bool Direct { get; set; }
    public Dictionary<string, JsonElement> Parameters { get; set; } = new();
    /// <summary>The fields of the operation, as the manifest gives them.</summary>
    public List<Field> Fields { get; set; } = new();

    [JsonIgnore] public Page? Page { get; set; }
    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string About => Words.Pick(DescriptionRu, Description);
    [JsonIgnore] public string Tip => Words.Pick(TooltipRu, Tooltip);
    [JsonIgnore] public string BlockName => Words.Pick(BlockRu, Block);
    [JsonIgnore] public bool Dangerous => Kind == "dangerous";

    /// <summary>The button of the operation is in sight only while the values of the form match (`visible_when` of its parameters).</summary>
    [JsonIgnore]
    public Dictionary<string, JsonElement>? VisibleWhen =>
        Parameters.TryGetValue("visible_when", out var condition) && condition.ValueKind == JsonValueKind.Object
            ? condition.EnumerateObject().ToDictionary(item => item.Name, item => item.Value) : null;

    /// <summary>
    /// The operation reads the lists of the form it stands in (`validate_fields` of its
    /// parameters; no key - it does). One that does not - it installs a tool, it exports what
    /// another list names - is not held back by a list with too few ticks. The door counts the
    /// same way (operation_model.short_selections).
    /// </summary>
    [JsonIgnore] public bool ValidatesFields => !(Parameters.TryGetValue("validate_fields", out var flag) && flag.ValueKind == JsonValueKind.False);

    /// <summary>The main action of its card (`primary` of its parameters).</summary>
    [JsonIgnore] public bool Primary => Parameters.TryGetValue("primary", out var primary) && primary.ValueKind == JsonValueKind.True;
}

public sealed class Field
{
    public string Id { get; set; } = "";
    /// <summary>The kind as the manifest names it: one of <see cref="FieldKinds.Known"/>.</summary>
    public string Kind { get; set; } = "";
    public JsonElement Default { get; set; }
    public JsonElement DefaultRu { get; set; }
    public JsonElement DefaultEn { get; set; }
    /// <summary>The block of the form the field stands in: `section` of the manifest.</summary>
    public string Group { get; set; } = "";
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Hint { get; set; } = "";
    public string HintRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    public string Placeholder { get; set; } = "";
    public double? Min { get; set; }
    public double? Max { get; set; }
    public double? Step { get; set; }
    public int MinSelected { get; set; }
    public int Rows { get; set; }
    /// <summary>In the values of the form, never drawn: another control owns it on the screen.</summary>
    public bool Hidden { get; set; }
    public Dictionary<string, JsonElement>? VisibleWhen { get; set; }
    public Dictionary<string, JsonElement>? HiddenWhen { get; set; }
    /// <summary>
    /// The conditions of the manifest of this program, as it writes them: a field is shown, hidden or
    /// switched off by the values of other fields (Core\Conditions.cs reads them; the console command
    /// applies the same rules to what it runs - system_core\core\operation_model.py).
    /// </summary>
    public JsonElement VisibleIf { get; set; }
    public JsonElement HiddenIf { get; set; }
    public JsonElement VisibleIfAny { get; set; }
    public JsonElement DisabledIf { get; set; }
    public JsonElement DisabledIfAny { get; set; }
    public JsonElement EnabledIf { get; set; }
    public List<Option> Options { get; set; } = new();
    /// <summary>The colours a slider is drawn in from end to end - what it does, in place of words (the manifest, `track`).</summary>
    public List<string> Track { get; set; } = new();

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Note => Words.Pick(HintRu, Hint);

    /// <summary>The tooltip: the short line of the manifest, then the full explanation.</summary>
    [JsonIgnore]
    public string Tip
    {
        get
        {
            var more = Words.Pick(TooltipRu, Tooltip);
            return Note.Length > 0 && more.Length > 0 ? Note + "\n\n" + more : Note.Length > 0 ? Note : more;
        }
    }

    /// <summary>The default in the language of the window (`default_ru` over `default`), as the manifest wrote it.</summary>
    [JsonIgnore]
    public JsonElement DefaultInUse
    {
        get
        {
            var local = Lang.Code == "ru" ? DefaultRu : DefaultEn;
            return local.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null ? Default : local;
        }
    }
}

public sealed class Option
{
    public JsonElement Value { get; set; }
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    /// <summary>A heading inside a long list, not a choice: it has no value.</summary>
    public bool Header { get; set; }
    /// <summary>A heading that is a line of explanation over the list and opens no block.</summary>
    public bool Note { get; set; }
    public string Tone { get; set; } = "";
    /// <summary>A colour the choice shows beside its name: "#cc0000".</summary>
    public string Swatch { get; set; } = "";

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Tip => Words.Pick(TooltipRu, Tooltip);
    /// <summary>The value as the text the form keeps and compares.</summary>
    [JsonIgnore] public string Key => FieldKinds.Text(Value);
}

public static class Words
{
    /// <summary>The Russian text in the Russian window; the English one otherwise, and wherever the Russian is missing.</summary>
    public static string Pick(string ru, string en) => Lang.Code == "ru" && ru.Length > 0 ? ru : en;
}

public static class FieldKinds
{
    /// <summary>The kinds of field the window can draw. Anything else is said in the journal, not left as an empty place.</summary>
    public static readonly string[] Known =
    {
        "checkbox", "checkboxes", "radio", "select", "number", "text", "textarea", "quality", "rgb_color", "slider",
    };

    /// <summary>A value of the manifest as text: a number without a tail of zeros, a flag as true or false.</summary>
    public static string Text(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString() ?? "",
        JsonValueKind.Number => value.GetDouble().ToString("0.############", CultureInfo.InvariantCulture),
        JsonValueKind.True => "true",
        JsonValueKind.False => "false",
        JsonValueKind.Null or JsonValueKind.Undefined => "",
        _ => value.GetRawText(),
    };

    /// <summary>`{field: value | [values]}`: every field named has one of its values.</summary>
    public static bool Matches(Dictionary<string, JsonElement>? condition, Func<string, string> valueOf)
    {
        if (condition is null || condition.Count == 0) return false;
        foreach (var (key, wanted) in condition)
        {
            var current = valueOf(key);
            bool any = wanted.ValueKind == JsonValueKind.Array
                ? wanted.EnumerateArray().Any(item => Text(item) == current)
                : Text(wanted) == current;
            if (!any) return false;
        }
        return true;
    }
}
