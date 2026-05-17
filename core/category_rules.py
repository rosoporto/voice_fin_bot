import re


GENERIC_CATEGORIES = {
    "другое",
    "покупка",
    "покупки",
    "прочее",
    "расход",
    "расходы",
    "трата",
    "траты",
}

KEYWORD_CATEGORIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(кредит|кредитк|кредитная\s+карт|плат[её]ж\s+по\s+карт)", re.I), "кредитка"),
    (re.compile(r"\b(заправк|бензин|топлив|дт|дизел)", re.I), "заправка"),
    (re.compile(r"\b(кофе|вода|чай|напит|сок|лимонад|кола|молочн[ыо]й\s+коктейль)", re.I), "напитки"),
    (re.compile(r"\b(конфет|шоколад|сладост|десерт|клубник.*глазур|морожен|печень|торт)", re.I), "сладости"),
)
BUSINESS_PREFIX = re.compile(r"^\s*бизнес\s*:\s*", re.I)


def infer_category(raw_text: str) -> str | None:
    for pattern, category in KEYWORD_CATEGORIES:
        if pattern.search(raw_text):
            return category
    return None


def should_override_category(
    category: str,
    raw_text: str,
    source_text: str | None = None,
) -> str | None:
    if is_business_transaction(raw_text, source_text):
        return "бизнес"

    inferred = infer_category(raw_text)
    if inferred is None:
        return None

    if category.casefold() in GENERIC_CATEGORIES:
        return inferred

    return None


def is_business_transaction(raw_text: str, source_text: str | None = None) -> bool:
    if BUSINESS_PREFIX.match(raw_text):
        return True

    if source_text is None:
        return False

    normalized_raw_text = _normalize_text(raw_text)
    for line in source_text.splitlines():
        if not BUSINESS_PREFIX.match(line):
            continue

        without_prefix = BUSINESS_PREFIX.sub("", line, count=1)
        if _normalize_text(without_prefix) == normalized_raw_text:
            return True

    return False


def _normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())
