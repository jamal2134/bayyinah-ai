import requests
from bs4 import BeautifulSoup
import json
import re


BASE_URL = "https://www.dorar.net"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "ar,en;q=0.9",
    "Referer": "https://www.dorar.net/hadith",
}


session = requests.Session()
session.headers.update(HEADERS)


# ==========================================================
# Clean text
# ==========================================================

def clean_text(text):

    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\u200f", "")
    text = text.replace("\u200e", "")
    text = text.replace("\ufeff", "")

    lines = []

    for line in text.splitlines():

        line = re.sub(
            r"[ \t]+",
            " ",
            line
        ).strip()

        if line:
            lines.append(line)

    return "\n".join(lines).strip()


# ==========================================================
# Get metadata field
# ==========================================================

def get_field(soup, field_name):

    for strong in soup.select("strong"):

        direct_text = " ".join(
            str(text).strip()
            for text in strong.find_all(
                string=True,
                recursive=False
            )
            if str(text).strip()
        )

        direct_text = clean_text(
            direct_text
        )

        if field_name not in direct_text:
            continue

        # Avoid:
        # المحدث
        # matching:
        # خلاصة حكم المحدث
        if (
            field_name == "المحدث"
            and "خلاصة حكم المحدث"
            in direct_text
        ):
            continue

        value = strong.select_one(
            ".primary-text-color"
        )

        if value:

            return clean_text(
                value.get_text(
                    " ",
                    strip=True
                )
            )

    return ""


# ==========================================================
# Get Hadith text
# ==========================================================

def extract_hadith(soup):

    article = soup.select_one(
        "article"
    )

    if not article:
        return ""

    text = clean_text(
        article.get_text(
            " ",
            strip=True
        )
    )

    # Remove result number if present
    text = re.sub(
        r"^\s*\d+\s*[-–—]\s*",
        "",
        text
    )

    return text


# ==========================================================
# Extract Sharh
# ==========================================================

def extract_sharh(soup):

    # Based on the working code:
    # explanation follows text-justify

    text_justify = soup.select_one(
        ".text-justify"
    )

    if text_justify:

        sharh_element = (
            text_justify.find_next_sibling()
        )

        if sharh_element:

            sharh = clean_text(
                sharh_element.get_text(
                    "\n",
                    strip=True
                )
            )

            if sharh:
                return sharh

    # ======================================================
    # Fallback 1
    # ======================================================

    selectors = [
        ".sharh",
        ".sharh-content",
        ".hadith-sharh",
        ".article-content",
        ".card-body"
    ]

    for selector in selectors:

        elements = soup.select(
            selector
        )

        for element in elements:

            text = clean_text(
                element.get_text(
                    "\n",
                    strip=True
                )
            )

            if len(text) >= 100:
                return text

    return ""


# ==========================================================
# Get explanation directly by ID
# ==========================================================

def get_sharh_by_id(
    sharh_id,
    hadith_id=""
):

    url = (
        f"{BASE_URL}/hadith/sharh/"
        f"{sharh_id}"
    )

    response = session.get(
        url,
        timeout=30
    )
    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # ======================================================
    # Hadith metadata
    # ======================================================

    hadith = extract_hadith(
        soup
    )

    narrator = get_field(
        soup,
        "الراوي"
    )

    scholar = get_field(
        soup,
        "المحدث"
    )

    source = get_field(
        soup,
        "المصدر"
    )

    page_or_number = get_field(
        soup,
        "الصفحة أو الرقم"
    )

    grade = get_field(
        soup,
        "خلاصة حكم المحدث"
    )

    takhrij = get_field(
        soup,
        "التخريج"
    )

    # ======================================================
    # Explanation
    # ======================================================

    sharh = extract_sharh(
        soup
    )

    return {

        "source":
            "Dorar Hadith Explanation",

        "hadith_id":
            hadith_id,

        "explanation_id":
            str(sharh_id),

        "hadith_text":
            hadith,

        "narrator":
            narrator,

        "scholar":
            scholar,

        "hadith_source":
            source,

        "page_or_number":
            page_or_number,

        "grade":
            grade,

        "takhrij":
            takhrij,

        "explanation":
            sharh,

        "url":
            url
    }


# ==========================================================
# Print
# ==========================================================

def print_result(result):

    print(
        "\n" + "=" * 80
    )

    print(
        "الحديث:"
    )

    print(
        result["hadith_text"]
        or "-"
    )

    print(
        "\nالراوي:"
    )

    print(
        result["narrator"]
        or "-"
    )

    print(
        "\nالمحدث:"
    )

    print(
        result["scholar"]
        or "-"
    )

    print(
        "\nالمصدر:"
    )

    print(
        result["hadith_source"]
        or "-"
    )

    print(
        "\nالحكم:"
    )

    print(
        result["grade"]
        or "-"
    )

    if result["takhrij"]:

        print(
            "\nالتخريج:"
        )

        print(
            result["takhrij"]
        )

    print(
        "\n" + "=" * 80
    )

    print(
        "شرح الحديث:"
    )

    print(
        "=" * 80
    )

    print(
        result["explanation"]
        or "لم يتم استخراج الشرح."
    )


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    sharh_id = input(
        "أدخل Explanation ID: "
    ).strip()

    if not sharh_id:

        print(
            "يجب إدخال Explanation ID."
        )

        raise SystemExit

    hadith_id = input(
        "أدخل Hadith ID (اختياري): "
    ).strip()

    try:

        result = get_sharh_by_id(
            sharh_id=sharh_id,
            hadith_id=hadith_id
        )

        print_result(
            result
        )

        output_file = (
            "dorar_hadith_explanation.json"
        )

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                result,
                file,
                ensure_ascii=False,
                indent=2
            )

        print(
            "\n" + "=" * 80
        )

        print(
            "تم حفظ النتيجة:"
        )

        print(
            output_file
        )

    except requests.exceptions.HTTPError as error:

        print(
            "\nHTTP ERROR:"
        )

        print(error)

    except requests.exceptions.RequestException as error:

        print(
            "\nCONNECTION ERROR:"
        )

        print(error)

    except Exception as error:

        print(
            "\nERROR:"
        )

        print(error)
