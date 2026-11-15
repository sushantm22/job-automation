from __future__ import annotations

import re
from typing import Any


def _strip_html(value: str) -> str:
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _parse_attrs(attr_string: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([A-Za-z0-9:_-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", attr_string):
        key = match.group(1)
        value = match.group(2) or match.group(3) or match.group(4) or ""
        attrs[key.lower()] = value
    return attrs


def _extract_label_map(html: str) -> dict[str, str]:
    label_map: dict[str, str] = {}
    for match in re.finditer(r"<label\b([^>]*)>(.*?)</label>", html, flags=re.I | re.S):
        attrs = _parse_attrs(match.group(1))
        label_for = attrs.get("for") or attrs.get("id")
        text = _strip_html(match.group(2))
        if label_for:
            label_map[label_for] = text
    return label_map


def _field_selector(name: str, field_id: str | None, field_type: str) -> str:
    if field_id:
        return f"#{field_id}"
    if name:
        return f"{field_type} [name='{name}']" if field_type not in {"radio", "checkbox"} else f"input[name='{name}']"
    return field_type


def _extract_select_options(html: str, field_name: str) -> list[str]:
    matches = re.findall(
        rf"<option\b[^>]*value\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))[^>]*>(.*?)</option>",
        html,
        flags=re.I | re.S,
    )
    options: list[str] = []
    for values in matches:
        option_value = next((part for part in values if part), "")
        if option_value:
            options.append(option_value)
    return options


def _extract_field_list(html: str) -> list[dict[str, Any]]:
    label_map = _extract_label_map(html)
    fields: list[dict[str, Any]] = []
    last_label = ""

    for match in re.finditer(r"<(input|select|textarea)\b([^>]*)>", html, flags=re.I | re.S):
        tag = match.group(1).lower()
        attrs = _parse_attrs(match.group(2))

        field_id = attrs.get("id")
        name = attrs.get("name") or field_id or ""
        field_type = (attrs.get("type") or tag).lower()
        if field_type in {"hidden", "submit", "button", "reset"}:
            continue

        label = (
            attrs.get("aria-label")
            or label_map.get(field_id or "")
            or label_map.get(name)
            or last_label
            or ""
        )
        last_label = label

        if tag == "select":
            option_values = []
            select_html = match.group(0)
            option_matches = re.findall(
                r"<option\b([^>]*)>(.*?)</option>",
                select_html + html[match.end(): match.end() + 500],
                flags=re.I | re.S,
            )
            for option_attrs, option_text in option_matches:
                option_attributes = _parse_attrs(option_attrs)
                option_value = option_attributes.get("value") or _strip_html(option_text)
                if option_value:
                    option_values.append(option_value)
            field = {
                "selector": _field_selector(name, field_id, "select"),
                "label": label,
                "name": name,
                "type": "select",
                "required": "required" in attrs,
                "options": option_values,
                "placeholder": attrs.get("placeholder", ""),
                "current_value": attrs.get("value", ""),
            }
        elif tag == "textarea":
            field = {
                "selector": _field_selector(name, field_id, "textarea"),
                "label": label,
                "name": name,
                "type": "textarea",
                "required": "required" in attrs,
                "options": [],
                "placeholder": attrs.get("placeholder", ""),
                "current_value": attrs.get("value", ""),
            }
        else:
            field = {
                "selector": _field_selector(name, field_id, field_type),
                "label": label,
                "name": name,
                "type": field_type if field_type in {"text", "email", "tel", "url", "date", "file", "radio", "checkbox"} else "text",
                "required": "required" in attrs,
                "options": [],
                "placeholder": attrs.get("placeholder", ""),
                "current_value": attrs.get("value", ""),
            }

        if field["name"]:
            fields.append(field)

    # Handle radio/checkbox groups with shared names and provide option lists.
    names: dict[str, list[str]] = {}
    for field in fields:
        if field["type"] in {"radio", "checkbox"}:
            names.setdefault(field["name"], [])
            value = field["current_value"]
            if value and value not in names[field["name"]]:
                names[field["name"]].append(value)

    for field in fields:
        if field["type"] in {"radio", "checkbox"}:
            field["options"] = names.get(field["name"], [])

    return fields


def extract_form_fields(html: str) -> list[dict[str, Any]]:
    return _extract_field_list(html)
