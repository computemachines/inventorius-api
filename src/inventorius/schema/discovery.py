"""Bounded catalog discovery; clients need not download the complete schema."""
import json


def discover_mixins(definition, *, query="", names=(), limit=10, offset=0):
    mixins = definition["mixins"]
    parents = {name: [] for name in mixins}
    for parent, mixin in mixins.items():
        for child in mixin.get("children", []):
            if child["mixin"] in parents:
                parents[child["mixin"]].append({"mixin": parent, "trigger": child["trigger"]})
    roots = set(definition["root_mixins"])
    words = query.casefold().split()
    candidates = []
    for name, mixin in mixins.items():
        if names and name not in names:
            continue
        search_text = json.dumps({"name": name, "fields": mixin["fields"], "parents": parents[name]}, ensure_ascii=False).casefold()
        if all(word in search_text for word in words):
            candidates.append(name)
    candidates.sort(key=lambda name: (name.casefold() != query.casefold(), name.casefold()))

    def paths(name):
        found, pending, truncated = [], [(name, [], frozenset())], False
        examined = 0
        while pending and len(found) < 8 and examined < 200:
            current, chain, seen = pending.pop()
            examined += 1
            if current in seen:
                truncated = True
                continue
            if current in roots:
                found.append({"root": current, "steps": chain})
            if len(chain) >= 12:
                truncated = True
                continue
            for parent in parents[current][:50]:
                step = {"parent": parent["mixin"], "child": current, "trigger": parent["trigger"]}
                pending.append((parent["mixin"], [step] + chain, seen | {current}))
            truncated |= len(parents[current]) > 50
        return {"paths": found, "truncated": truncated or bool(pending)}

    results = []
    for name in candidates[offset:offset + limit]:
        results.append({
            "name": name, "definition": mixins[name], "is_root": name in roots,
            "parents": parents[name], "activation": paths(name),
            "intersections": [rule for rule in definition["intersections"] if name in rule["when"]],
        })
    return {"matches": results, "total": len(candidates), "offset": offset,
            "has_more": offset + len(results) < len(candidates),
            "missing_names": [name for name in names if name not in mixins]}
