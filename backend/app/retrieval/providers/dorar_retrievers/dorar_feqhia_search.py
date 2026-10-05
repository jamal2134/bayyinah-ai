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
    "Referer": "https://dorar.net/feqhia",
}

session = requests.Session()
session.headers.update(HEADERS)


# ==========================================================
# Text cleaning
# ==========================================================

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\u200f", "")
    text = text.replace("\u200e", "")

    # Normalize spaces without destroying paragraphs
    lines = []

    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()

        if line:
            lines.append(line)

    return "\n".join(lines).strip()


# ==========================================================
# Search Dorar Feqhia
# ==========================================================

def search_feqhia(query):

    url = f"{BASE_URL}/feqhia/search"

    response = session.get(
        url,
        params={"q": query},
        timeout=30
    )

    print("=" * 80)
    print("Search Status:", response.status_code)
    print("Search URL:", response.url)
    print("=" * 80)

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    results = []
    seen_ids = set()

    # Search links pointing to /feqhia/{id}
    for link in soup.find_all("a", href=True):

        href = link.get("href", "").strip()

        match = re.search(
            r"/feqhia/(\d+)(?:[/?#]|$)",
            href
        )

        if not match:
            continue

        feqhia_id = match.group(1)

        if feqhia_id in seen_ids:
            continue

        title = clean_text(
            link.get_text(" ", strip=True)
        )

        if not title:
            continue

        seen_ids.add(feqhia_id)

        results.append({
            "feqhia_id": feqhia_id,
            "title": title,
            "url": f"{BASE_URL}/feqhia/{feqhia_id}"
        })

    return results


# ==========================================================
# Remove unwanted UI elements
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
        ".offcanvas"
    ]

    for selector in selectors:

        for element in soup.select(selector):
            element.decompose()


# ==========================================================
# Find relevant content container
# ==========================================================

def find_content_container(soup, expected_title=""):

    candidates = []

    selectors = [
        ".card-body",
        ".article-content",
        ".content",
        "article",
        "main"
    ]

    for selector in selectors:

        for element in soup.select(selector):

            text = clean_text(
                element.get_text(
                    "\n",
                    strip=True
                )
            )

            if len(text) < 100:
                continue

            score = 0

            # Prefer containers containing result title
            if (
                expected_title
                and expected_title[:30] in text
            ):
                score += 10000

            # Prefer smaller focused containers
            # over massive navigation containers
            score -= len(text) * 0.01

            # Reward evidence-related words
            evidence_terms = [
                "الأدلَّة",
                "الأدلة",
                "الدليل",
                "السنة",
                "السُّنَّة",
                "الإجماع",
                "المذهب",
                "القول",
                "رواه"
            ]

            for term in evidence_terms:
                if term in text:
                    score += 100

            candidates.append({
                "score": score,
                "length": len(text),
                "element": element,
                "selector": selector
            })

    if not candidates:
        return None, None

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    best = candidates[0]

    return (
        best["element"],
        best["selector"]
    )


# ==========================================================
# Remove trailing UI / related content
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

    stop_phrases = [
        "انظر أيضا:",
        "انظر أيضًا:",
        "السابق",
        "التالي"
    ]

    skip_exact = {
        "محتويات الصفحة",
        "الرابط",
        "المختصر"
    }

    for line in lines:

        if line in skip_exact:
            continue

        # Stop when reaching related-content section
        if any(
            line.startswith(phrase)
            for phrase in stop_phrases
        ):
            break

        cleaned.append(line)

    return "\n".join(cleaned).strip()


# ==========================================================
# Remove duplicated "Question & Answer" version
# ==========================================================

def remove_question_answer_duplicate(text):

    markers = [
        "المادة في سؤال وجواب",
        "المادة في سؤالٍ وجواب"
    ]

    for marker in markers:

        position = text.find(marker)

        if position != -1:

            # Keep original scholarly material
            # before Q&A repetition
            return text[:position].strip()

    return text


# ==========================================================
# Detect giant index/navigation pages
# ==========================================================

def is_index_page(content):

    if not content:
        return True

    navigation_terms = [
        "كتابُ الطَّهارة",
        "كِتابُ الصَّلاة",
        "كتابُ الزَّكاة",
        "كتابُ الصَّوم",
        "كتابُ الحَج",
        "كتابُ النِّكاح",
        "كتابُ البَيع",
        "كِتابُ المَواريث"
    ]

    matches = sum(
        1
        for term in navigation_terms
        if term in content
    )

    # A page containing many major books is
    # probably a broad index rather than evidence.
    if matches >= 4:
        return True

    # Extremely large content is usually
    # navigation/index contamination.
    if len(content) > 30000:
        return True

    return False


# ==========================================================
# Fetch one Feqhia page
# ==========================================================

def fetch_feqhia_page(result):

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

    remove_unwanted_elements(soup)

    container, selector = find_content_container(
        soup,
        result["title"]
    )

    if container is None:

        return {
            "status": "no_content",
            "content": ""
        }

    content = clean_text(
        container.get_text(
            "\n",
            strip=True
        )
    )

    # Remove UI
    content = trim_content(content)

    # Remove duplicated simplified Q&A
    content = remove_question_answer_duplicate(
        content
    )

    content = clean_text(content)

    # Detect broad index pages
    if is_index_page(content):

        return {
            "status": "index_page",
            "content": ""
        }

    if len(content) < 80:

        return {
            "status": "too_short",
            "content": content
        }

    return {
        "status": "ok",
        "content": content,
        "selector": selector
    }


# ==========================================================
# Export clean retrieval data
# ==========================================================

def retrieve_feqhia(query, max_results=15):

    search_results = search_feqhia(query)

    print(
        "\nSearch results:",
        len(search_results)
    )

    clean_results = []
    skipped_results = []

    rank = 0

    for index, result in enumerate(
        search_results[:max_results],
        start=1
    ):

        print(
            f"\n[{index}/{min(len(search_results), max_results)}]"
        )

        try:

            page = fetch_feqhia_page(
                result
            )

            if page["status"] != "ok":

                print(
                    "Skipped:",
                    page["status"]
                )

                skipped_results.append({
                    "feqhia_id":
                        result["feqhia_id"],

                    "title":
                        result["title"],

                    "url":
                        result["url"],

                    "reason":
                        page["status"]
                })

                continue

            rank += 1

            clean_results.append({

                "rank":
                    rank,

                "feqhia_id":
                    result["feqhia_id"],

                "title":
                    result["title"],

                "url":
                    result["url"],

                "content":
                    page["content"]
            })

            print(
                "OK | Content length:",
                len(page["content"])
            )

            time.sleep(0.4)

        except Exception as error:

            print(
                "ERROR:",
                error
            )

            skipped_results.append({

                "feqhia_id":
                    result["feqhia_id"],

                "title":
                    result["title"],

                "url":
                    result["url"],

                "reason":
                    str(error)
            })

    return {

        "source":
            "Dorar Feqhia",

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
        "اكتب المسألة الفقهية: "
    ).strip()

    if not query:

        print(
            "يجب إدخال مسألة فقهية."
        )

        raise SystemExit

    try:

        data = retrieve_feqhia(
            query=query,
            max_results=15
        )

        output_file = (
            "dorar_feqhia_clean.json"
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
            "Search results:",
            data["search_result_count"]
        )

        print(
            "Retrieved:",
            data["retrieved_count"]
        )

        print(
            "Skipped:",
            len(data["skipped"])
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