"""Turns a section schema into editor fields and a submitted editor back into content (WEB-04).

Field names: f.<key> (scalar), f.<key>.label / f.<key>.url (link), u.<key> (image upload),
             l.<key>.<row>.<sub> (list cell), lu.<key>.<row>.<sub> (list image upload).
"""

import re

from apps.core.uploads import save_public


def _scalar(post, files, name, upload_name, field):
    if field["type"] == "link":
        return {"label": post.get(f"{name}.label", ""), "url": post.get(f"{name}.url", "")}
    if field["type"] == "image":
        upload = files.get(upload_name)
        if upload:
            return save_public(upload, "website")
        return "" if post.get(f"{name}.clear") else post.get(name, "")
    return post.get(name, "")


def parse(schema, post, files):
    content = {}
    for field in schema:
        key = field["key"]
        if field["type"] != "list":
            content[key] = _scalar(post, files, f"f.{key}", f"u.{key}", field)
            continue
        rows = sorted({int(m.group(1)) for name in post for m in [re.match(rf"^l\.{key}\.(\d+)\.", name)] if m})
        content[key] = [
            {
                sub["key"]: _scalar(post, files, f"l.{key}.{i}.{sub['key']}", f"lu.{key}.{i}.{sub['key']}", sub)
                for sub in field["fields"]
            }
            for i in rows
        ]
    return content


def _cells(key, index, subs, row):
    return [
        {
            **sub,
            "value": (row or {}).get(sub["key"]),
            "name": f"l.{key}.{index}.{sub['key']}",
            "upload": f"lu.{key}.{index}.{sub['key']}",
        }
        for sub in subs
    ]


def editor_fields(schema, content):
    """Schema + current values + input names in one structure the template can loop over."""
    out = []
    for field in schema:
        key, value = field["key"], content.get(field["key"])
        if field["type"] == "list":
            rows = [_cells(key, i, field["fields"], row) for i, row in enumerate(value or [])]
            out.append({**field, "rows": rows, "template_row": _cells(key, "__INDEX__", field["fields"], None)})
        else:
            out.append({**field, "value": value, "name": f"f.{key}", "upload": f"u.{key}"})
    return out
