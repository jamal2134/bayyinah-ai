import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import quote, urljoin, urldefrag
import json
import re
import time


BASE_URL = "https://dorar.net"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "ar,en;q=0.9",
    "Referer": "https://dorar.net/tafseer",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


SECTION_NAMES = [
    "غريب الكلمات",
    "المعنى الإجمالي",
    "تفسير الآيات",
    "الفوائد التربوية",
    "الفوائد العلمية واللطائف",
    "بلاغة الآيات",
]


# ==========================================================
# Text cleaning
# ==========================================================

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)

    return text.strip()


# ==========================================================
# HTTP session
# ==========================================================

session = requests.Session()
session.headers.update(HEADERS)


# ==========================================================
# Search Tafseer
# ==========================================================

def search_tafseer(query):

    url = f"{BASE_URL}/tafseer/search"

    response = session.get(
        url,
        params={"q": query},
        timeout=30
    )

    print("Search HTTP Status:", response.status_code)
    print("Search URL:", response.url)

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    results = []
    seen = set()

    for link in soup.find_all("a", href=True):

        href = link.get("href", "").strip()

        # Only real Tafseer pages
        if "/tafseer/" not in href:
            continue

        # Ignore search/filter URLs
        if "/tafseer/search" in href:
            continue

        full_url = urljoin(
            BASE_URL,
            href
        )

        page_url, fragment = urldefrag(full_url)

        # Accept URLs such as:
        # /tafseer/2/25
        if not re.search(
            r"/tafseer/\d+(?:/\d+)?/?$",
            page_url
        ):
            continue

        search_match = clean_text(
            link.get_text(
                " ",
                strip=True
            )
        )

        if not search_match:
            continue

        key = (
            page_url,
            fragment,
            search_match
        )

        if key in seen:
            continue

        seen.add(key)

        results.append({
            "search_match": search_match,
            "url": full_url,
            "page_url": page_url,
            "fragment": fragment
        })

    return results


# ==========================================================
# Determine section name
# ==========================================================

def normalize_section_name(text):

    text = clean_text(text)

    for section in SECTION_NAMES:

        if section in text:
            return section

    return None


# ==========================================================
# Extract section following heading
# ==========================================================

def extract_after_heading(heading):

    parts = []

    current = heading.next_sibling

    while current:

        # Text node
        if isinstance(current, str):

            text = clean_text(current)

            if text:
                parts.append(text)

            current = current.next_sibling
            continue

        if not isinstance(current, Tag):
            current = current.next_sibling
            continue

        # Stop if another heading begins
        if current.name in [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6"
        ]:
            break

        # Also stop if this element itself
        # represents another known section
        possible_heading = normalize_section_name(
            current.get_text(
                " ",
                strip=True
            )
        )

        if (
            possible_heading
            and len(
                clean_text(
                    current.get_text(
                        " ",
                        strip=True
                    )
                )
            ) < 100
        ):
            break

        text = clean_text(
            current.get_text(
                "\n",
                strip=True
            )
        )

        if text:
            parts.append(text)

        current = current.next_sibling

    return clean_text(
        "\n".join(parts)
    )


# ==========================================================
# Find sections using headings
# ==========================================================

def extract_sections_by_headings(soup):

    sections = {}

    heading_tags = soup.find_all(
        [
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6"
        ]
    )

    for heading in heading_tags:

        heading_text = clean_text(
            heading.get_text(
                " ",
                strip=True
            )
        )

        section_name = normalize_section_name(
            heading_text
        )

        if not section_name:
            continue

        section_text = extract_after_heading(
            heading
        )

        if not section_text:
            continue

        # Avoid replacing larger useful content
        if section_name not in sections:

            sections[section_name] = section_text

        elif len(section_text) > len(
            sections[section_name]
        ):

            sections[section_name] = section_text

    return sections


# ==========================================================
# Extract sections using IDs such as #tt4
# ==========================================================

def extract_sections_by_ids(soup):

    sections = {}

    # Dorar pages can contain tt IDs
    elements = soup.find_all(
        id=re.compile(r"^tt\d+$")
    )

    for element in elements:

        # Try to find nearby heading/title
        heading_text = ""

        # element itself
        own_text = clean_text(
            element.get_text(
                " ",
                strip=True
            )
        )

        section_name = normalize_section_name(
            own_text
        )

        # previous heading
        if not section_name:

            previous_heading = element.find_previous(
                [
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6"
                ]
            )

            if previous_heading:

                heading_text = clean_text(
                    previous_heading.get_text(
                        " ",
                        strip=True
                    )
                )

                section_name = normalize_section_name(
                    heading_text
                )

        if not section_name:
            continue

        text = clean_text(
            element.get_text(
                "\n",
                strip=True
            )
        )

        if not text:
            continue

        if section_name not in sections:

            sections[section_name] = text

        elif len(text) > len(
            sections[section_name]
        ):

            sections[section_name] = text

    return sections


# ==========================================================
# Generic fallback section extraction
# ==========================================================

def extract_sections_fallback(soup):

    sections = {}

    for section_name in SECTION_NAMES:

        candidate = soup.find(
            string=lambda value:
                value
                and section_name
                in clean_text(value)
        )

        if not candidate:
            continue

        parent = candidate.parent

        if not parent:
            continue

        text = extract_after_heading(
            parent
        )

        if text:

            sections[section_name] = text

    return sections


# ==========================================================
# Merge section dictionaries
# ==========================================================

def merge_sections(*section_sets):

    merged = {}

    for section_set in section_sets:

        for name, text in section_set.items():

            text = clean_text(text)

            if not text:
                continue

            if name not in merged:
                merged[name] = text

            # Keep the largest useful version
            elif len(text) > len(
                merged[name]
            ):
                merged[name] = text

    return merged


# ==========================================================
# Extract Surah / Ayah information
# ==========================================================

def extract_page_identity(soup, page_url):

    page_title = ""

    if soup.title:

        page_title = clean_text(
            soup.title.get_text(
                " ",
                strip=True
            )
        )

    headings = []

    for heading in soup.find_all(
        ["h1", "h2", "h3"]
    ):

        text = clean_text(
            heading.get_text(
                " ",
                strip=True
            )
        )

        if text and text not in headings:
            headings.append(text)

    # URL numbers
    match = re.search(
        r"/tafseer/(\d+)(?:/(\d+))?",
        page_url
    )

    surah_id = None
    page_id = None

    if match:

        surah_id = int(
            match.group(1)
        )

        if match.group(2):

            page_id = int(
                match.group(2)
            )

    return {
        "page_title": page_title,
        "headings": headings,
        "surah_id": surah_id,
        "page_id": page_id
    }


# ==========================================================
# Extract Tafseer page
# ==========================================================

def extract_tafseer_page(page_url):

    response = session.get(
        page_url,
        timeout=30
    )

    print(
        "Fetching:",
        page_url,
        "Status:",
        response.status_code
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    # Remove irrelevant elements
    for element in soup.select(
        "script, style, nav, footer"
    ):
        element.decompose()

    identity = extract_page_identity(
        soup,
        page_url
    )

    # Try multiple extraction strategies

    sections1 = extract_sections_by_headings(
        soup
    )

    sections2 = extract_sections_by_ids(
        soup
    )

    sections3 = extract_sections_fallback(
        soup
    )

    sections = merge_sections(
        sections1,
        sections2,
        sections3
    )

    return {
        **identity,
        "sections": sections
    }


# ==========================================================
# Main Export
# ==========================================================

def export_tafseer(query):

    print("\n" + "=" * 80)
    print("البحث عن:", query)
    print("=" * 80)

    search_results = search_tafseer(
        query
    )

    print(
        "\nعدد نتائج البحث:",
        len(search_results)
    )

    final_results = []

    # Cache because several search results
    # can point to same Tafseer page
    page_cache = {}

    for index, result in enumerate(
        search_results,
        start=1
    ):

        print(
            f"\n[{index}/{len(search_results)}]"
        )

        page_url = result["page_url"]

        try:

            if page_url not in page_cache:

                page_cache[
                    page_url
                ] = extract_tafseer_page(
                    page_url
                )

                time.sleep(0.5)

            page_data = page_cache[
                page_url
            ]

            final_results.append({

                "search_match":
                    result["search_match"],

                "source_url":
                    result["url"],

                "page_url":
                    page_url,

                "matched_section":
                    result["fragment"],

                "surah_id":
                    page_data["surah_id"],

                "page_id":
                    page_data["page_id"],

                "page_title":
                    page_data["page_title"],

                "headings":
                    page_data["headings"],

                "sections":
                    page_data["sections"]
            })

        except Exception as error:

            print(
                "ERROR:",
                error
            )

            final_results.append({

                "search_match":
                    result["search_match"],

                "source_url":
                    result["url"],

                "page_url":
                    page_url,

                "error":
                    str(error)
            })

    # ------------------------------------------
    # Final JSON
    # ------------------------------------------

    output = {

        "source": "Dorar Tafseer",

        "query": query,

        "search_result_count":
            len(search_results),

        "unique_pages":
            len(page_cache),

        "results":
            final_results
    }

    return output


# ==========================================================
# Run
# ==========================================================

if __name__ == "__main__":

    query = input(
        "اكتب الآية أو كلمات البحث: "
    ).strip()

    if not query:

        print(
            "يجب إدخال نص للبحث."
        )

        exit()

    try:

        data = export_tafseer(
            query
        )

        output_file = (
            "dorar_tafseer_clean.json"
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

        print("\n" + "=" * 80)

        print("تم الانتهاء بنجاح.")

        print(
            "نتائج البحث:",
            data["search_result_count"]
        )

        print(
            "عدد الصفحات المختلفة:",
            data["unique_pages"]
        )

        print(
            "الملف:",
            output_file
        )

    except requests.exceptions.HTTPError as error:

        print("\nHTTP ERROR:")
        print(error)

    except requests.exceptions.RequestException as error:

        print("\nCONNECTION ERROR:")
        print(error)

    except Exception as error:

        print("\nERROR:")
        print(error)