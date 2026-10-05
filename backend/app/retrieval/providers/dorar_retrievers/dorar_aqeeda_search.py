import requests
from bs4 import BeautifulSoup
import json
import re
import time


BASE_URL = "https://dorar.net"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "ar,en;q=0.9",
    "Referer": "https://dorar.net/aqeeda",
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
# Search Aqeeda
# ==========================================================

def search_aqeeda(query):

    url = f"{BASE_URL}/aqeeda/search"

    response = session.get(
        url,
        params={"q": query},
        timeout=30
    )

    print("=" * 80)
    print(
        "Search Status:",
        response.status_code
    )
    print(
        "Search URL:",
        response.url
    )
    print("=" * 80)

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    results = []

    # Important:
    # same aqeeda ID may appear multiple times
    seen_ids = set()

    for link in soup.find_all(
        "a",
        href=True
    ):

        href = link.get(
            "href",
            ""
        ).strip()

        match = re.search(
            r"/aqeeda/(\d+)(?:[/?#]|$)",
            href
        )

        if not match:
            continue

        aqeeda_id = match.group(1)

        # Remove duplicate pages
        if aqeeda_id in seen_ids:
            continue

        title = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not title:
            continue

        seen_ids.add(
            aqeeda_id
        )

        results.append({
            "aqeeda_id":
                aqeeda_id,

            "title":
                title,

            "url":
                f"{BASE_URL}/aqeeda/{aqeeda_id}"
        })

    return results


# ==========================================================
# Remove UI elements
# ==========================================================

def remove_unwanted_elements(soup):

    selectors = [
        "script",
        "style",
        "nav",
        "header",
        "footer",
        "form",
        "button",
        "aside",
        "noscript",

        ".modal",
        ".breadcrumb",
        ".pagination",
        ".social",
        ".share",
        ".navbar",
        ".footer",
        ".header",
        ".sidebar",
        ".side-nav",
        ".offcanvas",
        ".fixed-bottom"
    ]

    for selector in selectors:

        for element in soup.select(
            selector
        ):

            element.decompose()


# ==========================================================
# Find focused content container
# ==========================================================

def find_content_container(
    soup,
    expected_title=""
):

    candidates = []

    selectors = [
        ".card-body",
        ".article-content",
        ".content",
        ".main-content",
        "article",
        "main"
    ]

    evidence_terms = [
        "قال الله",
        "قال تعالى",
        "الدليل",
        "الأدلة",
        "الأدلَّة",
        "القرآن",
        "القُرْآن",
        "السنة",
        "السُّنَّة",
        "الحديث",
        "الإجماع",
        "قال ابن",
        "قال شيخ",
        "قال الإمام",
        "قال رسول",
        "رواه"
    ]

    normalized_title = re.sub(
        r"^\d+\s*-\s*",
        "",
        expected_title
    ).strip()

    for selector in selectors:

        for element in soup.select(
            selector
        ):

            text = clean_text(
                element.get_text(
                    "\n",
                    strip=True
                )
            )

            if len(text) < 100:
                continue

            score = 0

            # Prefer content containing the
            # expected search title
            if normalized_title:

                title_piece = (
                    normalized_title[:35]
                )

                if title_piece in text:
                    score += 10000

            # Reward evidence-rich content
            for term in evidence_terms:

                if term in text:
                    score += 120

            # Prefer focused containers instead
            # of enormous index containers
            score -= (
                len(text) * 0.01
            )

            candidates.append({
                "score":
                    score,

                "length":
                    len(text),

                "element":
                    element,

                "selector":
                    selector
            })

    if not candidates:
        return None, None

    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    best = candidates[0]

    return (
        best["element"],
        best["selector"]
    )


# ==========================================================
# Trim navigation / related content
# ==========================================================

def trim_content(text):

    if not text:
        return ""

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    cleaned = []

    # When these sections appear after the
    # actual article, stop extraction
    stop_phrases = [
        "انظر أيضا:",
        "انظر أيضًا:",
        "مواضيع ذات صلة",
        "موضوعات ذات صلة",
        "السابق",
        "التالي"
    ]

    skip_exact = {
        "محتويات الصفحة",
        "الرابط",
        "المختصر",
        "مشاركة",
        "طباعة"
    }

    for line in lines:

        if line in skip_exact:
            continue

        should_stop = False

        for phrase in stop_phrases:

            if line.startswith(phrase):
                should_stop = True
                break

        if should_stop:
            break

        cleaned.append(
            line
        )

    return "\n".join(
        cleaned
    ).strip()


# ==========================================================
# Remove duplicated Q&A sections
# ==========================================================

def remove_question_answer_duplicate(
    text
):

    markers = [
        "المادة في سؤال وجواب",
        "المادة في سؤالٍ وجواب"
    ]

    for marker in markers:

        position = text.find(
            marker
        )

        if position != -1:

            return text[
                :position
            ].strip()

    return text


# ==========================================================
# Detect broad/index pages
# ==========================================================

def is_index_page(content):

    if not content:
        return True

    # Major book headings in Dorar Aqeeda encyclopedia
    major_book_terms = [
        "الكتابُ الأوَّلُ:",
        "الكِتابُ الثَّاني:",
        "الكتابُ الثَّالث",
        "الكِتابُ الرَّابِع",
        "الكِتابُ الخَامِس",
        "الكِتابُ السَّادِس",
        "الكِتابُ السَّابِع",
        "الكِتابُ الثَّامِن",
        "الكِتابُ التَّاسِع",
        "الكِتابُ العاشِر",
        "الكتابُ الحادي عشر",
        "الكتابُ الثَّاني عشر",
        "الكتابُ الثَّالث عشر"
    ]

    major_books_found = sum(
        1
        for term in major_book_terms
        if term in content
    )

    # If several encyclopedia books appear,
    # this is clearly navigation/index contamination.
    if major_books_found >= 3:
        return True

    # Another strong indication of encyclopedia navigation
    navigation_terms = [
        "الإيمانُ بالملائِكةِ",
        "الإيمانُ بالكُتُبِ",
        "الإيمانُ بالأنبياءِ",
        "الإيمانُ باليَومِ الآخِرِ",
        "الإيمانُ بالقَضاءِ والقَدَرِ",
        "نَواقِض الإيمانِ",
        "الشِّرْكُ - أقسامُه"
    ]

    navigation_matches = sum(
        1
        for term in navigation_terms
        if term in content
    )

    if navigation_matches >= 4:
        return True

    # Very large content is suspicious, but we use
    # a generous limit because valid Aqeeda pages
    # can themselves contain many evidences.
    if len(content) > 50000:
        return True

    return False
# ==========================================================
# Fetch one Aqeeda page
# ==========================================================

def fetch_aqeeda_page(result):

    url = result["url"]

    response = session.get(
        url,
        timeout=30
    )

    print(
        "Fetching:",
        url,
        "| Status:",
        response.status_code
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    remove_unwanted_elements(
        soup
    )

    container, selector = (
        find_content_container(
            soup,
            result["title"]
        )
    )

    if container is None:

        return {
            "status":
                "no_content",

            "content":
                ""
        }

    content = clean_text(
        container.get_text(
            "\n",
            strip=True
        )
    )

    content = trim_content(
        content
    )

    content = (
        remove_question_answer_duplicate(
            content
        )
    )

    content = clean_text(
        content
    )

    # Index detection
    if is_index_page(
        content
    ):

        return {
            "status":
                "index_page",

            "content":
                ""
        }

    # Very small result probably means
    # wrong container or no useful evidence
    if len(content) < 80:

        return {
            "status":
                "too_short",

            "content":
                content
        }

    return {
        "status":
            "ok",

        "content":
            content,

        "selector":
            selector
    }


# ==========================================================
# Retrieve clean Aqeeda evidence
# ==========================================================

def retrieve_aqeeda(
    query,
    max_results=15
):

    search_results = (
        search_aqeeda(
            query
        )
    )

    print(
        "\nUnique search pages:",
        len(search_results)
    )

    clean_results = []
    skipped_results = []

    rank = 0

    selected_results = (
        search_results[
            :max_results
        ]
    )

    total = len(
        selected_results
    )

    for index, result in enumerate(
        selected_results,
        start=1
    ):

        print(
            f"\n[{index}/{total}]"
        )

        try:

            page = (
                fetch_aqeeda_page(
                    result
                )
            )

            status = page[
                "status"
            ]

            if status != "ok":

                print(
                    "Skipped:",
                    status
                )

                skipped_results.append({
                    "aqeeda_id":
                        result[
                            "aqeeda_id"
                        ],

                    "title":
                        result[
                            "title"
                        ],

                    "url":
                        result[
                            "url"
                        ],

                    "reason":
                        status
                })

                continue

            rank += 1

            clean_results.append({

                "rank":
                    rank,

                "aqeeda_id":
                    result[
                        "aqeeda_id"
                    ],

                "title":
                    result[
                        "title"
                    ],

                "url":
                    result[
                        "url"
                    ],

                "content":
                    page[
                        "content"
                    ]
            })

            print(
                "OK | Content length:",
                len(
                    page["content"]
                )
            )

            # Be polite to server
            time.sleep(0.4)

        except Exception as error:

            print(
                "ERROR:",
                error
            )

            skipped_results.append({

                "aqeeda_id":
                    result[
                        "aqeeda_id"
                    ],

                "title":
                    result[
                        "title"
                    ],

                "url":
                    result[
                        "url"
                    ],

                "reason":
                    str(error)
            })

    return {

        "source":
            "Dorar Aqeeda",

        "query":
            query,

        "search_result_count":
            len(search_results),

        "retrieved_count":
            len(clean_results),

        "results":
            clean_results,

        "skipped":
            skipped_results
    }


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    query = input(
        "اكتب المسألة العقدية: "
    ).strip()

    if not query:

        print(
            "يجب إدخال مسألة عقدية."
        )

        raise SystemExit

    try:

        data = retrieve_aqeeda(
            query=query,
            max_results=15
        )

        output_file = (
            "dorar_aqeeda_clean.json"
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
            "تم الانتهاء بنجاح"
        )

        print(
            "Unique search pages:",
            data[
                "search_result_count"
            ]
        )

        print(
            "Retrieved:",
            data[
                "retrieved_count"
            ]
        )

        print(
            "Skipped:",
            len(
                data["skipped"]
            )
        )

        print(
            "Output:",
            output_file
        )

    except requests.exceptions.RequestException as error:

        print(
            "\nNETWORK ERROR:"
        )

        print(error)

    except Exception as error:

        print(
            "\nERROR:"
        )

        print(error)