import requests
from bs4 import BeautifulSoup
import json
import re
from urllib.parse import urljoin


BASE_URL = "https://dorar.net"
SEARCH_URL = f"{BASE_URL}/hadith/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "ar,en;q=0.9",
    "Referer": "https://dorar.net/hadith",
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

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n\s*\n+",
        "\n",
        text
    )

    return text.strip()


# ==========================================================
# Normalize for duplicate detection
# ==========================================================

def normalize_text(text):

    if not text:
        return ""

    # Arabic tashkeel
    text = re.sub(
        r"[\u0617-\u061A\u064B-\u0652\u0670]",
        "",
        text
    )

    # Tatweel
    text = text.replace("ـ", "")

    text = re.sub(
        r"[^\w\u0600-\u06FF]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip().lower()


# ==========================================================
# Get value from strong field
# ==========================================================

def get_field(block, field_name):

    # Search every strong field separately
    for strong in block.select("strong"):

        # Get only direct text of <strong>,
        # without text from nested spans/links
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

        # Example:
        # الراوي :
        # المحدث :
        # المصدر :
        # الصفحة أو الرقم :
        # خلاصة حكم المحدث :
        if field_name not in direct_text:
            continue

        # Important:
        # Avoid matching "المحدث" inside
        # "خلاصة حكم المحدث"
        if (
            field_name == "المحدث"
            and "خلاصة حكم المحدث"
            in direct_text
        ):
            continue

        # Dorar usually stores the actual
        # value inside primary-text-color
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

        # Fallback:
        # remove field label from full strong text
        full_text = clean_text(
            strong.get_text(
                " ",
                strip=True
            )
        )

        full_text = re.sub(
            rf"^\s*{re.escape(field_name)}\s*:\s*",
            "",
            full_text
        )

        return clean_text(
            full_text
        )

    return ""

# ==========================================================
# Extract direct hadith URL
# ==========================================================

def get_hadith_url(block):

    # Best option:
    # actual "عرض الحديث" link
    for link in block.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        )

        if re.fullmatch(
            r"/h/[A-Za-z0-9]+",
            href
        ):

            return urljoin(
                BASE_URL,
                href
            )

    # Fallback:
    # shareLink
    link = block.select_one(
        "a.shareLink[href]"
    )

    if link:

        href = link.get(
            "href",
            ""
        )

        # remove query parameters
        href = href.split("?")[0]

        return urljoin(
            BASE_URL,
            href
        )

    return ""


# ==========================================================
# Extract hadith ID from URL
# ==========================================================

def get_hadith_id(url):

    if not url:
        return ""

    match = re.search(
        r"/h/([A-Za-z0-9]+)",
        url
    )

    if match:
        return match.group(1)

    return ""


# ==========================================================
# Extract hadith number
# ==========================================================

def extract_result_number(
    heading_text
):

    match = re.match(
        r"^\s*(\d+)\s*[-–—]",
        heading_text
    )

    if match:
        return int(
            match.group(1)
        )

    return None


# ==========================================================
# Clean hadith text
# ==========================================================

def extract_hadith_text(block):

    heading = block.select_one(
        "article h5.h5-responsive"
    )

    if not heading:
        return ""

    text = clean_text(
        heading.get_text(
            " ",
            strip=True
        )
    )

    # Remove Dorar result number:
    # 1 - حديث...
    text = re.sub(
        r"^\s*\d+\s*[-–—]\s*",
        "",
        text
    )

    return clean_text(text)


# ==========================================================
# Extract Takhrij
# ==========================================================

def get_takhrij(block):

    return get_field(
        block,
        "التخريج"
    )


# ==========================================================
# Extract categories
# ==========================================================

def get_categories(block):

    categories = []

    for link in block.select(
        'a[href*="/hadith-category/cat/"]'
    ):

        category = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if (
            category
            and category not in categories
        ):
            categories.append(
                category
            )

    return categories


# ==========================================================
# Detect explanation availability
# ==========================================================

def get_explanation(block):

    explanation = block.select_one(
        "a.xplain"
    )

    if not explanation:

        return {
            "available": False,
            "xplain_id": ""
        }

    return {
        "available": True,
        "xplain_id": explanation.get(
            "xplain",
            ""
        )
    }


# ==========================================================
# Parse one result
# ==========================================================

def parse_hadith_block(block):

    heading = block.select_one(
        "article h5.h5-responsive"
    )

    if not heading:
        return None

    raw_heading = clean_text(
        heading.get_text(
            " ",
            strip=True
        )
    )

    hadith_text = (
        extract_hadith_text(
            block
        )
    )

    narrator = get_field(
        block,
        "الراوي"
    )

    scholar = get_field(
        block,
        "المحدث"
    )

    source = get_field(
        block,
        "المصدر"
    )

    page_or_number = get_field(
        block,
        "الصفحة أو الرقم"
    )

    grade = get_field(
        block,
        "خلاصة حكم المحدث"
    )

    takhrij = get_takhrij(
        block
    )

    url = get_hadith_url(
        block
    )

    hadith_id = get_hadith_id(
        url
    )

    categories = get_categories(
        block
    )

    explanation = get_explanation(
        block
    )

    # ======================================================
    # Strict validation
    # ======================================================

    # A real Dorar result must have:
    # hadith + narrator + scholar + source
    if not hadith_text:
        return None

    if not narrator:
        return None

    if not scholar:
        return None

    if not source:
        return None

    return {

        "result_number":
            extract_result_number(
                raw_heading
            ),

        "hadith_id":
            hadith_id,

        "hadith_text":
            hadith_text,

        "narrator":
            narrator,

        "scholar":
            scholar,

        "source":
            source,

        "page_or_number":
            page_or_number,

        "grade":
            grade,

        "takhrij":
            takhrij,

        "categories":
            categories,

        "explanation_available":
            explanation[
                "available"
            ],

        "explanation_id":
            explanation[
                "xplain_id"
            ],

        "url":
            url
    }


# ==========================================================
# Search Dorar
# ==========================================================

def search_hadith(
    query,
    max_results=20
):

    response = session.get(
        SEARCH_URL,
        params={
            "q": query
        },
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # ======================================================
    # IMPORTANT
    # Actual specialist search results
    # ======================================================

    specialist = soup.select_one(
        "#specialist"
    )

    if not specialist:

        return []

    # Each actual result is directly represented
    # by this block
    blocks = specialist.select(
        "div.border-bottom.py-4"
    )

    results = []

    seen = set()

    for block in blocks:

        result = parse_hadith_block(
            block
        )

        if not result:
            continue

        # ==================================================
        # Duplicate detection
        # ==================================================

        if result["hadith_id"]:

            duplicate_key = (
                "id",
                result["hadith_id"]
            )

        else:

            duplicate_key = (
                normalize_text(
                    result[
                        "hadith_text"
                    ]
                ),
                normalize_text(
                    result[
                        "narrator"
                    ]
                ),
                normalize_text(
                    result[
                        "scholar"
                    ]
                ),
                normalize_text(
                    result[
                        "source"
                    ]
                ),
                normalize_text(
                    result[
                        "grade"
                    ]
                )
            )

        if duplicate_key in seen:
            continue

        seen.add(
            duplicate_key
        )

        results.append(
            result
        )

        if len(results) >= max_results:
            break

    return results


# ==========================================================
# Build final clean JSON
# ==========================================================

def retrieve_hadith(
    query,
    max_results=15
):

    results = search_hadith(
        query=query,
        max_results=max_results
    )

    final_results = []

    for rank, result in enumerate(
        results,
        start=1
    ):

        result["rank"] = rank

        # Put rank first
        ordered = {
            "rank":
                rank,

            "hadith_id":
                result[
                    "hadith_id"
                ],

            "hadith_text":
                result[
                    "hadith_text"
                ],

            "narrator":
                result[
                    "narrator"
                ],

            "scholar":
                result[
                    "scholar"
                ],

            "source":
                result[
                    "source"
                ],

            "page_or_number":
                result[
                    "page_or_number"
                ],

            "grade":
                result[
                    "grade"
                ],

            "takhrij":
                result[
                    "takhrij"
                ],

            "categories":
                result[
                    "categories"
                ],

            "explanation_available":
                result[
                    "explanation_available"
                ],

            "explanation_id":
                result[
                    "explanation_id"
                ],

            "url":
                result[
                    "url"
                ]
        }

        final_results.append(
            ordered
        )

    return {

        "source":
            "Dorar Hadith",

        "query":
            query,

        "retrieved_count":
            len(final_results),

        "results":
            final_results
    }


# ==========================================================
# Print results
# ==========================================================

def print_results(data):

    print(
        "\nعدد النتائج:",
        data["retrieved_count"]
    )

    for result in data["results"]:

        print(
            "\n" + "=" * 80
        )

        print(
            "النتيجة رقم:",
            result["rank"]
        )

        print(
            "=" * 80
        )

        print(
            "نص الحديث:"
        )

        print(
            result["hadith_text"]
        )

        print(
            "\nالراوي:",
            result["narrator"]
        )

        print(
            "المحدث:",
            result["scholar"]
        )

        print(
            "المصدر:",
            result["source"]
        )

        print(
            "الصفحة أو الرقم:",
            result["page_or_number"]
        )

        print(
            "حكم المحدث:",
            result["grade"]
        )

        if result["takhrij"]:

            print(
                "التخريج:",
                result["takhrij"]
            )

        if result["categories"]:

            print(
                "التصنيفات:",
                " | ".join(
                    result["categories"]
                )
            )

        print(
            "شرح متاح:",
            result[
                "explanation_available"
            ]
        )

        if result["url"]:

            print(
                "الرابط:",
                result["url"]
            )


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    query = input(
        "اكتب الحديث أو جزءًا منه: "
    ).strip()

    if not query:

        print(
            "يجب إدخال نص للبحث."
        )

        raise SystemExit

    try:

        data = retrieve_hadith(
            query=query,
            max_results=15
        )

        print_results(
            data
        )

        output_file = (
            "dorar_hadith_clean.json"
        )

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )

        print(
            "\n" + "=" * 80
        )

        print(
            "تم الانتهاء بنجاح."
        )

        print(
            "Retrieved:",
            data[
                "retrieved_count"
            ]
        )

        print(
            "Output:",
            output_file
        )

        print(
            "Debug:",
            "hadith_search_debug.html"
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
