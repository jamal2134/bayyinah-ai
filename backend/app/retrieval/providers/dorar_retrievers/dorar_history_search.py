import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json
import re


BASE_URL = "https://dorar.net"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "ar,en;q=0.9",
    "Referer": "https://dorar.net/history",
    "Connection": "keep-alive",
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
# Extract year information
# ==========================================================

def extract_years(container):

    hijri_year = ""
    gregorian_year = ""

    strong_tags = container.find_all("strong")

    for strong in strong_tags:

        text = clean_text(
            strong.get_text(
                " ",
                strip=True
            )
        )

        # Hijri year
        if "العام الهجري" in text:

            text = text.replace(
                "العام الهجري",
                ""
            )

            text = text.replace(
                ":",
                ""
            )

            hijri_year = clean_text(text)

        # Gregorian year
        elif "العام الميلادي" in text:

            text = text.replace(
                "العام الميلادي",
                ""
            )

            text = text.replace(
                ":",
                ""
            )

            gregorian_year = clean_text(text)

    return hijri_year, gregorian_year


# ==========================================================
# Extract title
# ==========================================================

def extract_title(container):

    heading = container.find(
        ["h5", "h6"]
    )

    if not heading:
        return ""

    # Remove icons
    for icon in heading.find_all("i"):
        icon.decompose()

    title = clean_text(
        heading.get_text(
            " ",
            strip=True
        )
    )

    # Remove final dot if present
    title = title.rstrip(".").strip()

    return title


# ==========================================================
# Extract details
# ==========================================================

def extract_details(container):

    body = container.select_one(
        ".card-body"
    )

    if not body:
        return ""

    # History page normally puts
    # event details inside <p>
    paragraphs = body.find_all("p")

    texts = []

    for paragraph in paragraphs:

        text = clean_text(
            paragraph.get_text(
                " ",
                strip=True
            )
        )

        if text:
            texts.append(text)

    if texts:
        return clean_text(
            "\n".join(texts)
        )

    return ""


# ==========================================================
# Extract event URL
# ==========================================================

def extract_event_url(container, event_id):

    # نبحث فقط عن رابط الحدث نفسه
    for link in container.find_all("a", href=True):

        href = link.get("href", "")

        if re.fullmatch(
            r"/history/event/\d+",
            href
        ):
            return urljoin(
                BASE_URL,
                href
            )

    # fallback
    if event_id:
        return (
            f"{BASE_URL}/history/event/{event_id}"
        )

    return ""

# ==========================================================
# Search History
# ==========================================================

def search_history(query):

    url = (
        f"{BASE_URL}"
        f"/history/search"
    )

    response = session.get(
        url,
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
    # KEY FIX
    # ======================================================

    event_containers = soup.select(
        ".event-container"
    )

    results = []

    for container in event_containers:

        event_id = container.get(
            "data-event-id",
            ""
        )

        title = extract_title(
            container
        )

        hijri_year, gregorian_year = (
            extract_years(
                container
            )
        )

        details = extract_details(
            container
        )

        event_url = extract_event_url(
            container,
            event_id
        )

        # Ignore completely empty items
        if not (
            title
            or details
            or event_id
        ):
            continue

        result = {

            "event_id":
                event_id,

            "title":
                title,

            "hijri_year":
                hijri_year,

            "gregorian_year":
                gregorian_year,

            "details":
                details,

            "url":
                event_url
        }

        results.append(
            result
        )

    return results


# ==========================================================
# Print result
# ==========================================================

def print_results(results):

    print(
        "\nعدد النتائج:",
        len(results)
    )

    for index, result in enumerate(
        results,
        start=1
    ):

        print(
            "\n" + "=" * 80
        )

        print(
            f"النتيجة رقم {index}"
        )

        print("=" * 80)

        print(
            "Event ID:",
            result["event_id"]
        )

        print(
            "العنوان:",
            result["title"]
        )

        print(
            "العام الهجري:",
            result["hijri_year"]
        )

        print(
            "العام الميلادي:",
            result["gregorian_year"]
        )

        print(
            "الرابط:",
            result["url"]
        )

        print(
            "\nتفاصيل الحدث:"
        )

        print(
            result["details"]
        )


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    query = input(
        "اكتب الحدث أو الموضوع التاريخي: "
    ).strip()

    if not query:

        print(
            "يجب إدخال نص للبحث."
        )

        exit()

    try:

        results = search_history(
            query
        )

        print_results(
            results
        )

        # ==================================================
        # JSON
        # ==================================================

        output = {

            "source":
                "Dorar History",

            "query":
                query,

            "count":
                len(results),

            "results":
                results
        }

        output_file = (
            "dorar_history_results.json"
        )

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                output,
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
            "عدد النتائج:",
            len(results)
        )

        print(
            "تم إنشاء:"
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
