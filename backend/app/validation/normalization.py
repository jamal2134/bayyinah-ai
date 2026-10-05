import re
import unicodedata


ARABIC_MARKS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)

SOURCE_ALIASES = {
    "sahih al bukhari": "bukhari",
    "sahih bukhari": "bukhari",
    "صحيح البخاري": "bukhari",
    "البخاري": "bukhari",
    "jami al tirmidhi": "tirmidhi",
    "sunan al tirmidhi": "tirmidhi",
    "الترمذي": "tirmidhi",
    "جامع الترمذي": "tirmidhi",
    "sahih muslim": "muslim",
    "صحيح مسلم": "muslim",
    "مسلم": "muslim",
}


def normalize(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ـ", "")
    text = ARABIC_MARKS.sub("", text)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"}))
    return re.sub(r"\s+", " ", PUNCTUATION.sub(" ", text)).strip()


def normalize_surah(value: object) -> str:
    text = normalize(value)
    for prefix in ("سورة ", "سوره ", "surah ", "sura "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    aliases = {
        "1": "الفاتحة", "2": "البقرة", "3": "ال عمران", "18": "الكهف",
        "67": "الملك", "112": "الاخلاص", "113": "الفلق", "114": "الناس",
        "al fatiha": "الفاتحة", "al baqarah": "البقرة", "al mulk": "الملك",
        "the cow": "البقرة",
        "17": "الاسراء", "الاسراء": "الاسراء", "بني اسرائيل": "الاسراء",
        "40": "غافر", "غافر": "غافر", "المؤمن": "غافر", "المومن": "غافر",
        "94": "الشرح", "الشرح": "الشرح", "الانشراح": "الشرح",
        "111": "المسد", "المسد": "المسد", "تبت": "المسد",
    }
    return aliases.get(text, text)


def normalize_source(value: object) -> str:
    text = normalize(value)
    return SOURCE_ALIASES.get(text, text)


def integer(value: object) -> int | None:
    match = re.search(r"\d+", normalize(value))
    return int(match.group()) if match else None


def compound_parts(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s+(?:and|و)\s+|[,&+]", value, flags=re.I) if part.strip()]
