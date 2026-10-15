using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;

namespace AudionImageTools.Core;

/// <summary>
/// The conditions of a field as the manifest of this program writes them:
/// <c>visible_if: {field: scale_mode, equals: custom}</c>,
/// <c>disabled_if: {field: to, not_contains_any: [jpg, webp]}</c>, <c>all</c> and <c>any</c> over a
/// list of such. The same rules as system_core\core\operation_model.py (`matches`): the window
/// applies them to what it shows, the console command to what it runs - and the command is the
/// judge: a field the window showed by mistake is not told to the engine all the same.
/// </summary>
public static class Conditions
{
    static bool Given(JsonElement condition) => condition.ValueKind == JsonValueKind.Object;

    static List<string> Listed(JsonElement value) =>
        value.ValueKind == JsonValueKind.Array ? value.EnumerateArray().Select(FieldKinds.Text).ToList() : new List<string> { FieldKinds.Text(value) };

    /// <summary>Whether the condition holds for the values of the page. What it does not understand holds.</summary>
    public static bool Holds(JsonElement condition, Values values)
    {
        if (!Given(condition)) return true;
        if (condition.TryGetProperty("all", out var all) && all.ValueKind == JsonValueKind.Array)
            return all.EnumerateArray().All(item => Holds(item, values));
        if (condition.TryGetProperty("any", out var any) && any.ValueKind == JsonValueKind.Array)
            return any.EnumerateArray().Any(item => Holds(item, values));
        string key = condition.TryGetProperty("field", out var named) ? FieldKinds.Text(named)
            : condition.TryGetProperty("id", out var byId) ? FieldKinds.Text(byId) : "";
        if (key.Length == 0) return true;

        // What the field holds: one text, or - for a list of ticks - its items.
        bool list = values.Find(key) is { } field && Values.IsList(field);
        string actual = values.Knows(key) ? values.Get(key)
            : condition.TryGetProperty("default", out var fallback) ? Values.TextOf(fallback) : "";
        var items = list ? actual.Split(Values.ListSeparator, StringSplitOptions.RemoveEmptyEntries).ToList() : new List<string> { actual };

        if (condition.TryGetProperty("equals", out var equals)) return !list && Listed(equals).Contains(actual);
        if (condition.TryGetProperty("not_equals", out var notEquals)) return list || !Listed(notEquals).Contains(actual);
        if (condition.TryGetProperty("in", out var within))
            return within.ValueKind == JsonValueKind.Array && items.Any(Listed(within).Contains);
        if (condition.TryGetProperty("not_in", out var notIn))
            return notIn.ValueKind != JsonValueKind.Array || items.All(item => !Listed(notIn).Contains(item));
        if (condition.TryGetProperty("contains", out var contains)) return Listed(contains).Any(items.Contains);
        if (condition.TryGetProperty("not_contains", out var notContains)) return Listed(notContains).All(item => !items.Contains(item));
        if (condition.TryGetProperty("contains_any", out var containsAny))
            return containsAny.ValueKind == JsonValueKind.Array && Listed(containsAny).Any(items.Contains);
        if (condition.TryGetProperty("not_contains_any", out var notContainsAny))
            return notContainsAny.ValueKind != JsonValueKind.Array || Listed(notContainsAny).All(item => !items.Contains(item));
        if (condition.TryGetProperty("contains_all", out var containsAll))
            return containsAll.ValueKind == JsonValueKind.Array && Listed(containsAll).All(items.Contains);
        return true;
    }

    static bool AnyHolds(JsonElement several, Values values) =>
        several.ValueKind == JsonValueKind.Array && several.EnumerateArray().Any(item => Holds(item, values));

    /// <summary>The field is shown by the conditions of the manifest.</summary>
    public static bool Visible(Field field, Values values)
    {
        if (Given(field.VisibleIf) && !Holds(field.VisibleIf, values)) return false;
        if (Given(field.HiddenIf) && Holds(field.HiddenIf, values)) return false;
        if (field.VisibleIfAny.ValueKind == JsonValueKind.Array && !AnyHolds(field.VisibleIfAny, values)) return false;
        return true;
    }

    /// <summary>The field is switched off: in sight, and not to be set.</summary>
    public static bool Disabled(Field field, Values values)
    {
        if (Given(field.DisabledIf) && Holds(field.DisabledIf, values)) return true;
        if (AnyHolds(field.DisabledIfAny, values)) return true;
        if (Given(field.EnabledIf) && !Holds(field.EnabledIf, values)) return true;
        return false;
    }

    /// <summary>The fields the conditions of this one name: when one of them changes, the form is another form.</summary>
    public static IEnumerable<string> FieldsOf(Field field)
    {
        foreach (var condition in new[] { field.VisibleIf, field.HiddenIf, field.VisibleIfAny, field.DisabledIf, field.DisabledIfAny, field.EnabledIf })
            foreach (var name in Named(condition)) yield return name;
    }

    static IEnumerable<string> Named(JsonElement condition)
    {
        if (condition.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in condition.EnumerateArray())
                foreach (var name in Named(item)) yield return name;
            yield break;
        }
        if (condition.ValueKind != JsonValueKind.Object) yield break;
        foreach (var part in new[] { "all", "any" })
            if (condition.TryGetProperty(part, out var several))
                foreach (var name in Named(several)) yield return name;
        if (condition.TryGetProperty("field", out var named)) yield return FieldKinds.Text(named);
        else if (condition.TryGetProperty("id", out var byId)) yield return FieldKinds.Text(byId);
    }
}
