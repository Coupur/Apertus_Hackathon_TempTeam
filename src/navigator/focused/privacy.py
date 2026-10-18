"""Contact details are excluded from focused records and model evidence."""
import re

EMAIL = re.compile(r"[\w.+%-]+\s*(?:@|\(at\)|\[at\])\s*[\w.-]+\.[A-Za-z]{2,}", re.I)
PHONE = re.compile(r"(?<!\w)(?:\+|00)\d[\d ()/.\-]{7,}\d|\b(?:phone|tel(?:ephone)?|fax|telefon)\s*:?\s*\(?\d[\d ()/.\-]{6,}\d", re.I)
CONTACT_KEYS = {"email", "emails", "phone", "phones", "telephone", "fax", "contact_email", "contact_phone"}


def has_contact(text: str) -> bool:
    return bool(EMAIL.search(text) or PHONE.search(text))


def clean_text(text: str) -> str:
    # Keep a paragraph boundary at removed contact lines so extraction cannot
    # splice a role heading onto a name from the other side of a contact block.
    kept, contact_label = [], False
    for line in text.splitlines():
        if re.fullmatch(r"(?:mail|e-mail|email|phone\d*|telephone|telefon|fax)\s*:?",line.strip(),re.I):
            contact_label = True
            kept.append("")
            continue
        if has_contact(line) or (contact_label and re.fullmatch(r"[\d\s()+/.-]{6,}",line.strip())):
            contact_label = False
            kept.append("")
            continue
        if line.strip(): contact_label = False
        kept.append(line)
    return "\n".join(kept).strip("\n")


def public_record(value):
    """Read legacy payloads without leaking their old contact fields."""
    if isinstance(value, dict):
        return {k: public_record(v) for k, v in value.items() if k.lower() not in CONTACT_KEYS and not re.fullmatch(r"(?:phone|email|fax)\d+",k,re.I)}
    if isinstance(value, list):
        return [public_record(v) for v in value]
    return clean_text(value) if isinstance(value, str) else value
