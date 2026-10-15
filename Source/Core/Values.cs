using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AudionImageTools.Core;

/// <summary>
/// The values of the fields of one page, by the id of a field and not by the operation: a button
/// placed beside another reads the fields of that one. A value belongs to its page: what is set on
/// one page is not seen on another. The few fields the layout names `shared` are kept by the window
/// instead, one value for every page (<see cref="ValueStore"/>). The values live as long as the
/// window and are not written to the disk - every start begins with the defaults of the manifest.
/// A value is kept as text: a flag as "true" or "false", a number without a tail of zeros, a
/// group of ticks as its values joined by a line break.
/// </summary>
public sealed class Values
{
    /// <summary>The store of the window, for the fields named in <see cref="_shared"/>; null - this is that store.</summary>
    readonly Values? _window;
    readonly HashSet<string> _shared;

    readonly Dictionary<string, string> _held = new();
    /// <summary>Every field the page has met, by its id: a condition may name a field that is not drawn.</summary>
    readonly Dictionary<string, Field> _known = new();

    /// <summary>A value was changed: the id of its field.</summary>
    public event Action<string>? Changed;

    public const char ListSeparator = '\n';

    /// <summary>The values of the window itself: the fields that are one for every page, and the operations of the header.</summary>
    public Values() => _shared = new HashSet<string>();

    /// <summary>The values of a page; the fields named in <paramref name="shared"/> are kept by the window.</summary>
    public Values(Values window, IEnumerable<string> shared)
    {
        _window = window;
        _shared = new HashSet<string>(shared);
        // A shared field changed, on whichever page: this page hears it as a change of its own.
        window.Changed += id => { if (_shared.Contains(id)) Changed?.Invoke(id); };
    }

    /// <summary>Who keeps the value of a field: the window for a shared one, this page for every other.</summary>
    Values Home(string id) => _window is not null && _shared.Contains(id) ? _window : this;

    public static bool IsList(Field field) => field.Kind == "checkboxes";

    public void Learn(IEnumerable<Field> fields)
    {
        foreach (var field in fields) _known.TryAdd(field.Id, field);
    }

    /// <summary>The page holds a value for this id or has met its field: a condition that names another id reads its own default.</summary>
    public bool Knows(string id) => Home(id)._held.ContainsKey(id) || _known.ContainsKey(id);

    /// <summary>A field the page has met, by its id; null for one it has not.</summary>
    public Field? Find(string id) => _known.TryGetValue(id, out var field) ? field : null;

    /// <summary>A value of the manifest as the text this class keeps: a list as its items joined by a line break.</summary>
    public static string TextOf(JsonElement value) => value.ValueKind == JsonValueKind.Array
        ? string.Join(ListSeparator, value.EnumerateArray().Select(FieldKinds.Text)) : FieldKinds.Text(value);

    /// <summary>The default of a field as the text this class keeps.</summary>
    public static string DefaultOf(Field field)
    {
        var value = field.DefaultInUse;
        if (IsList(field))
            return value.ValueKind == JsonValueKind.Array ? string.Join(ListSeparator, value.EnumerateArray().Select(FieldKinds.Text)) : "";
        if (value.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            // No default written: a flag is off, a choice stands on its first option, a text is empty.
            if (field.Kind == "checkbox") return "false";
            if (field.Kind is "radio" or "select" && field.Options.Count > 0) return field.Options[0].Key;
            return "";
        }
        return FieldKinds.Text(value);
    }

    public string Get(Field field) => Home(field.Id)._held.TryGetValue(field.Id, out var value) ? value : DefaultOf(field);

    /// <summary>The value of a field by its id alone: what a condition asks. "" for a field the page has not met.</summary>
    public string Get(string id) =>
        Home(id)._held.TryGetValue(id, out var value) ? value : _known.TryGetValue(id, out var field) ? DefaultOf(field) : "";

    public bool IsOn(Field field) => Get(field) == "true";

    public HashSet<string> Picked(Field field) =>
        Get(field).Split(ListSeparator, StringSplitOptions.RemoveEmptyEntries).ToHashSet();

    public bool IsChanged(Field field) => Get(field) != DefaultOf(field);

    /// <summary>The person sets a field.</summary>
    public void Set(Field field, string value)
    {
        Learn(new[] { field });
        var home = Home(field.Id);
        if (Get(field) == value) return;
        // A value equal to the default is not held.
        if (value == DefaultOf(field)) home._held.Remove(field.Id);
        else home._held[field.Id] = value;
        home.Changed?.Invoke(field.Id);
    }

    /// <summary>Back to the defaults of the manifest.</summary>
    public void Reset(IEnumerable<Field> fields)
    {
        foreach (var field in fields)
        {
            var home = Home(field.Id);
            if (home._held.Remove(field.Id)) home.Changed?.Invoke(field.Id);
        }
    }

    /// <summary>
    /// The first list in sight with fewer ticks than its field asks for (`min_selected`); null
    /// when every list has enough - or the operation reads none of them (Node.ValidatesFields).
    /// </summary>
    public Field? TooFew(Node node, Func<Field, bool> inSight) =>
        !node.ValidatesFields ? null
        : node.Fields.FirstOrDefault(field => IsList(field) && field.MinSelected > 0 && inSight(field) && Picked(field).Count < field.MinSelected);

    /// <summary>The values of an operation as the door reads them (--params): every field of its form by its id, in the type the field has.</summary>
    public string ForDoor(Node node)
    {
        var payload = new JsonObject();
        foreach (var field in node.Fields) payload[field.Id] = Json(field);
        return payload.ToJsonString(new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
    }

    JsonNode? Json(Field field)
    {
        if (!IsChanged(field))
        {
            var raw = field.DefaultInUse;
            if (raw.ValueKind is not (JsonValueKind.Undefined or JsonValueKind.Null)) return JsonNode.Parse(raw.GetRawText());
        }
        var text = Get(field);
        return field.Kind switch
        {
            "checkbox" => JsonValue.Create(text == "true"),
            "number" or "quality" or "slider" => Number(text),
            "checkboxes" => new JsonArray(text.Split(ListSeparator, StringSplitOptions.RemoveEmptyEntries).Select(item => (JsonNode?)JsonValue.Create(item)).ToArray()),
            // A choice goes as the manifest wrote its value: a number stays a number.
            "radio" or "select" => field.Options.FirstOrDefault(option => option.Key == text) is { } option
                ? JsonNode.Parse(option.Value.GetRawText()) : JsonValue.Create(text),
            _ => JsonValue.Create(text),
        };
    }

    static JsonNode Number(string text)
    {
        if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) return JsonValue.Create(text);
        return number == Math.Floor(number) && Math.Abs(number) < 1e15 ? JsonValue.Create((long)number) : JsonValue.Create(number);
    }

    /// <summary>The fields of an operation that are not at their defaults, as "--set" would name them.</summary>
    public Dictionary<string, string> ChangedOf(Node node)
    {
        var changed = new Dictionary<string, string>();
        foreach (var field in node.Fields)
            if (IsChanged(field)) changed[field.Id] = Get(field).Replace(ListSeparator, ',');
        return changed;
    }
}

/// <summary>
/// The values of the whole window: a store for every page, and one of the window itself for the
/// fields the layout names `shared` (config\window_layout.yaml) and for the operations of the
/// header, which stand on no page.
/// </summary>
public sealed class ValueStore
{
    readonly HashSet<string> _shared;
    readonly Dictionary<string, Values> _pages = new();

    public ValueStore(IEnumerable<string>? shared = null) => _shared = new HashSet<string>(shared ?? Array.Empty<string>());

    /// <summary>The values of the window itself.</summary>
    public Values Window { get; } = new();

    /// <summary>A page by its section and its own id: the ids of pages repeat across sections.</summary>
    public static string KeyOf(Page page) => (page.Section?.Id ?? "") + "/" + page.Id;

    /// <summary>The values of a page; of the window, for an operation that stands on none.</summary>
    public Values Of(Page? page)
    {
        if (page is null) return Window;
        if (!_pages.TryGetValue(KeyOf(page), out var values)) _pages[KeyOf(page)] = values = new Values(Window, _shared);
        return values;
    }

    /// <summary>A page comes into sight: its fields are known before anything reads them - a condition may name a field of another operation of the page.</summary>
    public Values Open(Page page)
    {
        var values = Of(page);
        foreach (var node in page.Operations) values.Learn(node.Fields);
        return values;
    }
}
