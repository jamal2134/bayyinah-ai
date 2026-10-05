import pytest

from app.agents.claim_extractor import ClaimExtractor
from conftest import FakeClient, claim, valid_result


def grouped(text, claim_type, domain, attributes):
    item = claim(text=text, claim_type=claim_type, domain=domain)
    item["attributes"] = [{"type": kind, "value": value} for kind, value in attributes]
    return item


@pytest.mark.parametrize("text,claim_type,domain,attributes", [
    (
        "حديث «إنما الأعمال بالنيات» من رواية عمر بن الخطاب وأخرجه البخاري.",
        "HADITH_RECORD", "HADITH",
        [("TEXT", "إنما الأعمال بالنيات"), ("NARRATOR", "عمر بن الخطاب"),
         ("SOURCE", "صحيح البخاري")],
    ),
    (
        "حديث فضل سورة الملك وصفه الكاتب بأنه صحيح.",
        "HADITH_RECORD", "HADITH",
        [("TEXT", "فضل سورة الملك"), ("AUTHENTICITY", "صحيح")],
    ),
    (
        "حديث الأعمال بالنيات عن عمر، رواه البخاري، وهو صحيح.",
        "HADITH_RECORD", "HADITH",
        [("TEXT", "الأعمال بالنيات"), ("NARRATOR", "عمر"),
         ("SOURCE", "البخاري"), ("AUTHENTICITY", "صحيح")],
    ),
    (
        "آية الكرسي هي الآية 255 من سورة البقرة.",
        "QURAN_RECORD", "QURAN",
        [("SURAH", "البقرة"), ("AYAH_NUMBER", "255")],
    ),
    (
        "Surah الملك has 30 آيات and is a Makki surah.",
        "QURAN_RECORD", "QURAN",
        [("VERSE_COUNT", "30"), ("REVELATION_PERIOD", "Makki")],
    ),
    (
        "الوتر واجب عند الحنفية وسنة مؤكدة عند الشافعية.",
        "FIQH_RULING", "FIQH",
        [("SCHOOL", "الحنفية: واجب"), ("SCHOOL", "الشافعية: سنة مؤكدة")],
    ),
    (
        "غزوة بدر وقعت في السنة الثانية وكان عدد المسلمين 313.",
        "ISLAMIC_HISTORY", "HISTORY",
        [("DATE", "السنة الثانية للهجرة"), ("OTHER", "عدد المسلمين 313")],
    ),
])
def test_same_subject_attributes_remain_one_claim(settings, text, claim_type, domain, attributes):
    output = grouped(text, claim_type, domain, attributes)
    result = ClaimExtractor(settings, FakeClient([valid_result([output])])).extract(text)
    assert result.claim_count == 1
    assert result.claims[0].claim_type.value == claim_type
    assert [(item.type.value, item.value) for item in result.claims[0].attributes] == attributes


def test_unrelated_subjects_remain_separate(settings):
    quran = grouped("آية الكرسي هي الآية 255 من البقرة.", "QURAN_RECORD", "QURAN",
                    [("SURAH", "البقرة"), ("AYAH_NUMBER", "255")])
    fiqh = grouped("صلاة الوتر واجبة عند الحنفية.", "FIQH_RULING", "FIQH",
                   [("SCHOOL", "الحنفية"), ("RULING", "واجبة")])
    fiqh["id"] = "claim_002"
    result = ClaimExtractor(settings, FakeClient([valid_result([quran, fiqh], "ar")])).extract(
        "آية الكرسي هي الآية 255 من البقرة، وصلاة الوتر واجبة عند الحنفية."
    )
    assert result.claim_count == 2
    assert {item.domain.value for item in result.claims} == {"QURAN", "FIQH"}


def test_duplicates_ignore_diacritics_whitespace_and_punctuation(settings):
    first = claim(text="سورةُ الملكِ ثلاثون آيةً.")
    second = claim("claim_002", text="سورة الملك  ثلاثون آية")
    result = ClaimExtractor(settings, FakeClient([valid_result([first, second], "ar")])).extract("duplicate")
    assert result.claim_count == 1


def test_context_fragment_is_rejected_then_retried_as_complete_claim(settings):
    fragment = claim(text="رواه البخاري", claim_type="HADITH_ATTRIBUTION", domain="HADITH")
    complete = grouped(
        "حديث «إنما الأعمال بالنيات» عن عمر ورواه البخاري.", "HADITH_RECORD", "HADITH",
        [("TEXT", "إنما الأعمال بالنيات"), ("NARRATOR", "عمر"), ("SOURCE", "البخاري")],
    )
    client = FakeClient([valid_result([fragment], "ar"), valid_result([complete], "ar")])
    result = ClaimExtractor(settings, client).extract(complete["original_text"])
    assert result.claim_count == 1
    assert result.claims[0].claim_type.value == "HADITH_RECORD"
    assert "self-contained" in client.messages.calls[1]["messages"][0]["content"]


def test_athar_authenticity_is_officially_supported(settings):
    item = grouped("أثر ابن عباس وصفه المؤلف بأنه صحيح.", "ATHAR_RECORD", "ATHAR",
                   [("NARRATOR", "ابن عباس"), ("AUTHENTICITY", "صحيح")])
    result = ClaimExtractor(settings, FakeClient([valid_result([item], "ar")])).extract(item["original_text"])
    assert result.claims[0].domain.value == "ATHAR"
    assert result.claims[0].claim_type.value == "ATHAR_RECORD"


def test_shared_athar_authenticity_is_attached_to_each_report(settings):
    first = grouped("ورد عن ابن عباس أثر في الحسنة.", "ATHAR_TEXT", "ATHAR",
                    [("NARRATOR", "ابن عباس"), ("TEXT", "أثر في الحسنة")])
    second = grouped("ورد عن الحسن البصري أثر في محاسبة النفس.", "ATHAR_ATTRIBUTION", "ATHAR",
                     [("NARRATOR", "الحسن البصري"), ("TEXT", "محاسبة النفس")])
    second["id"] = "claim_002"
    authenticity = grouped("قال المؤلف إن هذين الأثرين صحيحان.", "ATHAR_AUTHENTICITY", "ATHAR",
                           [("AUTHENTICITY", "صحيحان")])
    authenticity["id"] = "claim_003"
    result = ClaimExtractor(
        settings, FakeClient([valid_result([first, second, authenticity], "ar")])
    ).extract("shared authenticity")
    assert result.claim_count == 2
    assert all(item.claim_type.value == "ATHAR_RECORD" for item in result.claims)
    assert all(any(attr.type.value == "AUTHENTICITY" for attr in item.attributes) for item in result.claims)

