import re

from bookmarks.models import Tag


def parse_tag_names(raw) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,，]", raw) if isinstance(raw, str) else list(raw)

    seen: set[str] = set()
    names: list[str] = []
    for part in parts:
        name = str(part).strip()
        if not name:
            continue
        name = name[:64]
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def get_or_create_tag(owner, name: str) -> Tag:
    name = name.strip()[:64]
    tag = Tag.objects.filter(owner=owner, name__iexact=name).first()
    if tag:
        return tag
    return Tag.objects.create(owner=owner, name=name)


def get_or_create_tags(owner, names: list[str]) -> list[Tag]:
    return [get_or_create_tag(owner, name) for name in parse_tag_names(names)]
