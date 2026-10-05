from bs4 import BeautifulSoup


LABELS = {
    "الراوي": "narrator", "المحدث": "scholar", "المصدر": "source",
    "الصفحة أو الرقم": "reference", "خلاصة حكم المحدث": "judgment",
}


def parse_dorar_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html or "", "html.parser")
    containers = soup.select(".hadith, .result, .hadith-info")
    if not containers and soup.get_text(" ", strip=True):
        containers = [soup]
    records = []
    for container in containers:
        record = {"hadith": "", "narrator": None, "scholar": None, "source": None,
                  "reference": None, "judgment": None}
        text_node = container.select_one(".hadith-text, .text, h5")
        record["hadith"] = text_node.get_text(" ", strip=True) if text_node else ""
        for line in container.get_text("\n", strip=True).splitlines():
            line = line.strip(" |-\u200f")
            for label, field in LABELS.items():
                if line.startswith(label):
                    record[field] = line.split(":", 1)[-1].strip() if ":" in line else line[len(label):].strip(" :")
        if not record["hadith"]:
            first = next((line.strip() for line in container.get_text("\n", strip=True).splitlines()
                          if not any(line.strip().startswith(label) for label in LABELS)), "")
            record["hadith"] = first
        if record["hadith"]:
            records.append(record)
    return records

