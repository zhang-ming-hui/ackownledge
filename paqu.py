import csv
import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "data"
SKILL_MD_DIR = DATA_DIR / "skill_md"
BASE_URL = "https://skills.sh/"
CHECKPOINT_FILE = str(DATA_DIR / "skills_checkpoint.json")
OUTPUT_JSON = str(DATA_DIR / "skills_data.json")
OUTPUT_CSV = str(DATA_DIR / "skills_data.csv")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

DETAIL_URL_RE = re.compile(r"^https://(?:www\.)?skills\.sh/([^/]+)/([^/]+)/([^/]+)$")
COMPACT_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\s*[KMB]?\b", re.I)
METRIC_PLACEHOLDER_VALUES = {"-", "\u2013", "\u2014", "N/A", "NA", "NONE"}
NEXT_PUSH_BLOCK_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)


def normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def safe_print(message: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    safe_message = message.encode(encoding, errors="replace").decode(
        encoding, errors="replace"
    )
    print(safe_message)


def clean_metric_field(text: Optional[str], label: str) -> Optional[str]:
    if not text:
        return None
    normalized = normalize_text(text)
    if not normalized:
        return None
    if normalized.upper() in METRIC_PLACEHOLDER_VALUES:
        return None
    normalized = re.sub(r"\bSource\b.*$", "", normalized, flags=re.I).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?\s*[KMB]?", normalized, flags=re.I):
        return normalized
    label_pattern = re.compile(re.escape(label), re.I)
    label_parts = label_pattern.split(normalized)
    search_space = label_parts[-1] if len(label_parts) > 1 else normalized
    matches = COMPACT_NUMBER_RE.findall(search_space)
    if not matches and search_space is not normalized:
        matches = COMPACT_NUMBER_RE.findall(normalized)
    if not matches:
        return None
    token = matches[-1] if label.lower() == "github stars" else matches[0]
    return normalize_text(token)


def parse_compact_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    s = normalize_text(text).upper().replace(",", "")
    if s in METRIC_PLACEHOLDER_VALUES:
        return None
    match = re.fullmatch(r"([\d.]+)\s*([KMB]?)", s)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit == "K":
        number *= 1_000
    elif unit == "M":
        number *= 1_000_000
    elif unit == "B":
        number *= 1_000_000_000
    return int(number)


def infer_category(skill_name: str, repo: str, description: str) -> Optional[str]:
    text = f"{skill_name} {repo} {description}".lower()
    rules = [
        (
            "frontend",
            [
                "frontend", "react", "vue", "ui", "ux", "css", "tailwind",
                "design", "nextjs", "next.js", "figma", "mobile", "android", "ios",
            ],
        ),
        (
            "document",
            ["pdf", "docx", "pptx", "xlsx", "document", "slides", "resume", "cv", "markdown"],
        ),
        (
            "cloud",
            ["azure", "cloud", "kubernetes", "infra", "devops", "deployment", "docker", "terraform"],
        ),
        (
            "marketing",
            ["marketing", "seo", "content", "copywriting", "pricing", "brand", "ads", "growth", "social"],
        ),
        (
            "coding",
            ["debug", "test", "typescript", "code", "review", "development", "refactor", "git", "github"],
        ),
        ("browser", ["browser", "scrape", "crawl", "search", "puppeteer", "playwright"]),
        ("agent", ["agent", "subagent", "workflow", "skills", "automation", "assistant"]),
        ("data", ["analysis", "excel", "sheet", "data", "sql", "postgres", "metrics", "dashboard", "report"]),
    ]
    for category, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return category
    return None


def create_driver(headless: bool = True):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,2200")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--lang=en-US")
    return webdriver.Chrome(options=options)


def canonicalize_github_repo_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return None
    owner, repo = segments[0], segments[1]
    repo = repo.removesuffix(".git")
    return f"https://github.com/{owner}/{repo}"


def find_repo_url(page_html: str, owner: str, repo: str) -> Optional[str]:
    owner_repo = f"/{owner}/{repo}".lower()
    fallback_url = None
    for href in re.findall(r'href="(https?://[^"]+)"', page_html, flags=re.I):
        if "github.com" not in href.lower():
            continue
        canonical = canonicalize_github_repo_url(href)
        if not canonical:
            continue
        if urlparse(canonical).path.lower() == owner_repo:
            return canonical
        if fallback_url is None:
            fallback_url = canonical
    return fallback_url


def normalize_record(record: Dict) -> Dict:
    normalized = dict(record)
    for field in [
        "skill_name", "owner", "repo", "description", "category",
        "detail_url", "repo_url", "first_seen", "github_stars",
        "skill_md",
    ]:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = normalize_text(value)

    for field in [
        "skill_md_html",
        "skill_md_raw_text",
        "skill_md_preview",
        "skill_md_rest",
        "skill_md_html_path",
        "skill_md_raw_text_path",
        "skill_md_text_path",
        "skill_md_source",
    ]:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = value.strip()

    normalized["weekly_installs"] = clean_metric_field(
        normalized.get("weekly_installs"), "Weekly Installs"
    )
    normalized["github_stars"] = clean_metric_field(
        normalized.get("github_stars"), "GitHub Stars"
    )
    normalized["repo_url"] = canonicalize_github_repo_url(normalized.get("repo_url"))
    normalized["weekly_installs_num"] = parse_compact_number(normalized.get("weekly_installs"))
    normalized["github_stars_num"] = parse_compact_number(normalized.get("github_stars"))

    if not normalized.get("category"):
        normalized["category"] = infer_category(
            str(normalized.get("skill_name", "")),
            str(normalized.get("repo", "")),
            str(normalized.get("description", "")),
        )
    return normalized


def normalize_records(records: List[Dict]) -> List[Dict]:
    return [normalize_record(record) for record in records]


def slugify_path_component(value: str) -> str:
    value = normalize_text(value).lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-._")
    return value or "skill"


def _skill_md_storage_dir(record: Dict) -> Path:
    skill_name = str(record.get("skill_name") or "")
    skill_id = str(record.get("skill_id") or "")
    slug = slugify_path_component(skill_name)[:80]
    dir_name = f"{slug}-{skill_id}" if skill_id else slug
    return SKILL_MD_DIR / dir_name


def _relative_to_data(path: Path) -> str:
    return path.relative_to(DATA_DIR).as_posix()


def externalize_skill_md_assets(record: Dict) -> Dict:
    prepared = dict(record)
    skill_md_html = prepared.pop("skill_md_html", "") or ""
    skill_md_raw_text = prepared.pop("skill_md_raw_text", "") or ""
    skill_md_preview = prepared.pop("skill_md_preview", "") or ""
    skill_md_rest = prepared.pop("skill_md_rest", "") or ""
    skill_md_text = prepared.get("skill_md", "") or ""

    existing_html_path = prepared.get("skill_md_html_path", "") or ""
    existing_raw_path = prepared.get("skill_md_raw_text_path", "") or ""
    existing_text_path = prepared.get("skill_md_text_path", "") or ""

    if not any([skill_md_html, skill_md_raw_text, skill_md_text, existing_html_path, existing_raw_path, existing_text_path]):
        return prepared

    storage_dir = _skill_md_storage_dir(prepared)
    storage_dir.mkdir(parents=True, exist_ok=True)

    if skill_md_html:
        html_path = storage_dir / "skill.md.html"
        html_path.write_text(skill_md_html, encoding="utf-8")
        prepared["skill_md_html_path"] = _relative_to_data(html_path)
    elif existing_html_path:
        prepared["skill_md_html_path"] = existing_html_path

    raw_payload = skill_md_raw_text or "\n\n".join(part for part in [skill_md_preview, skill_md_rest] if part).strip()
    if raw_payload:
        raw_path = storage_dir / "skill.md.raw.txt"
        raw_path.write_text(raw_payload, encoding="utf-8")
        prepared["skill_md_raw_text_path"] = _relative_to_data(raw_path)
    elif existing_raw_path:
        prepared["skill_md_raw_text_path"] = existing_raw_path

    if skill_md_text:
        text_path = storage_dir / "skill.md.txt"
        text_path.write_text(skill_md_text, encoding="utf-8")
        prepared["skill_md_text_path"] = _relative_to_data(text_path)
    elif existing_text_path:
        prepared["skill_md_text_path"] = existing_text_path

    prepared.pop("skill_md_preview", None)
    prepared.pop("skill_md_rest", None)
    prepared.pop("skill_md", None)
    return prepared


def load_checkpoint() -> Dict:
    if not Path(CHECKPOINT_FILE).exists():
        return {"detail_urls": [], "records": [], "failed_urls": []}
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def save_checkpoint(data: Dict) -> None:
    payload = dict(data)
    if "records" in payload and isinstance(payload["records"], list):
        payload["records"] = normalize_records(payload["records"])
    Path(CHECKPOINT_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def save_outputs(records: List[Dict]) -> None:
    records = [externalize_skill_md_assets(record) for record in normalize_records(records)]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)

    fieldnames = [
        "skill_id", "skill_name", "owner", "repo", "description",
        "skill_md_text_path", "skill_md_raw_text_path", "skill_md_html_path",
        "skill_md_source",
        "category", "detail_url", "repo_url", "first_seen", "weekly_installs",
        "github_stars", "weekly_installs_num", "github_stars_num",
    ]
    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {key: record.get(key) for key in fieldnames}
            for record in records
        )


def extract_field_by_label(page_text: str, label: str, next_labels: List[str]) -> Optional[str]:
    lines = [normalize_text(line) for line in page_text.splitlines()]
    lines = [line for line in lines if line]
    normalized_label = normalize_text(label).casefold()
    next_label_set = {
        normalize_text(next_label).casefold()
        for next_label in next_labels
        if normalize_text(next_label)
    }
    start_index = None
    for index, line in enumerate(lines):
        if line.casefold() == normalized_label:
            start_index = index + 1
            break
    if start_index is None:
        return None
    values: List[str] = []
    for line in lines[start_index:]:
        if line.casefold() in next_label_set:
            break
        values.append(line)
    value = normalize_text(" ".join(values))
    return value if value else None


def get_html_with_retry(url: str, retries: int = 3, timeout: int = 20) -> str:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            curl = subprocess.run(
                ["curl.exe", "-L", url],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            if curl.returncode == 0 and curl.stdout:
                return curl.stdout

            request = Request(url, headers=HEADERS)
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_err = exc
            safe_print(f"[RETRY {attempt}/{retries}] {url} -> {exc}")
            time.sleep(1.5 * attempt)
    raise last_err


def strip_html_to_text(page_html: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", "\n", page_html)
    text = re.sub(r"(?is)<style\b.*?</style>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(
        r"(?i)</(p|div|section|article|li|ul|ol|h1|h2|h3|h4|h5|h6|pre|code|main|nav|header|footer)>",
        "\n",
        text,
    )
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def extract_skill_md_from_html_block(page_html: str) -> Dict[str, str]:
    marker = "SKILL.md</span></div><div><div"
    idx = page_html.find(marker)
    if idx == -1:
        return {
            "skill_md_html": "",
            "skill_md_raw_text": "",
            "skill_md": "",
            "skill_md_source": "missing",
        }

    block_start = page_html.find(">", idx + len(marker))
    if block_start == -1:
        return {
            "skill_md_html": "",
            "skill_md_raw_text": "",
            "skill_md": "",
            "skill_md_source": "missing",
        }
    block_start += 1

    block_end = page_html.find('<div class="relative">', block_start)
    if block_end == -1:
        block_end = page_html.find("<button", block_start)
    if block_end == -1:
        return {
            "skill_md_html": "",
            "skill_md_raw_text": "",
            "skill_md": "",
            "skill_md_source": "missing",
        }

    block_html = page_html[block_start:block_end]
    raw_text = strip_html_to_text(block_html)
    text = normalize_text(raw_text)
    return {
        "skill_md_html": block_html,
        "skill_md_raw_text": raw_text,
        "skill_md": text,
        "skill_md_source": "html_block" if text else "missing",
    }


def _decode_next_payload_fragment(raw_fragment: str) -> str:
    try:
        decoded = json.loads('"' + raw_fragment + '"')
    except json.JSONDecodeError:
        decoded = raw_fragment.encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore")
    return html.unescape(decoded)


def _html_fragment_to_text(fragment: str) -> str:
    return normalize_text(strip_html_to_text(fragment)) if fragment else ""


def extract_skill_markdown_sections(page_html: str) -> Dict[str, str]:
    preview_anchor = 'previewHtml\\":\\"$'.replace("\\\\", "\\")
    rest_anchor = 'restHtml\\":\\"$'.replace("\\\\", "\\")
    preview_idx = page_html.find(preview_anchor)
    rest_idx = page_html.find(rest_anchor, preview_idx if preview_idx != -1 else 0)
    if preview_idx == -1 or rest_idx == -1:
        return {
            "skill_md_html": "",
            "skill_md_raw_text": "",
            "skill_md_preview": "",
            "skill_md_rest": "",
            "skill_md": "",
            "skill_md_source": "missing",
        }

    def _read_marker(start_idx: int, anchor: str) -> str:
        start = start_idx + len(anchor)
        end = start
        while end < len(page_html) and page_html[end].isalnum():
            end += 1
        return page_html[start:end]

    preview_marker = _read_marker(preview_idx, preview_anchor)
    rest_marker = _read_marker(rest_idx, rest_anchor)
    if not preview_marker or not rest_marker:
        return {
            "skill_md_html": "",
            "skill_md_raw_text": "",
            "skill_md_preview": "",
            "skill_md_rest": "",
            "skill_md": "",
            "skill_md_source": "missing",
        }

    preview_match = re.search(
        rf'self\.__next_f\.push\(\[1,"{re.escape(preview_marker)}:T[0-9a-f]+,"\]\)</script><script>self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>',
        page_html,
        re.I | re.S,
    )
    rest_match = re.search(
        rf'self\.__next_f\.push\(\[1,"{re.escape(rest_marker)}:T[0-9a-f]+,"\]\)</script><script>self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>',
        page_html,
        re.I | re.S,
    )

    preview_fragment = _decode_next_payload_fragment(preview_match.group(1)) if preview_match else ""
    rest_fragment = _decode_next_payload_fragment(rest_match.group(1)) if rest_match else ""
    preview_raw_text = strip_html_to_text(preview_fragment) if preview_fragment else ""
    rest_raw_text = strip_html_to_text(rest_fragment) if rest_fragment else ""
    preview_text = normalize_text(preview_raw_text) if preview_raw_text else ""
    rest_text = normalize_text(rest_raw_text) if rest_raw_text else ""
    full_html = "".join(part for part in [preview_fragment, rest_fragment] if part)
    full_raw_text = "\n\n".join(part for part in [preview_raw_text, rest_raw_text] if part).strip()
    full_text = normalize_text(full_raw_text) if full_raw_text else ""
    return {
        "skill_md_html": full_html,
        "skill_md_raw_text": full_raw_text,
        "skill_md_preview": preview_text,
        "skill_md_rest": rest_text,
        "skill_md": full_text,
        "skill_md_source": "next_stream" if full_text else "missing",
    }


def collect_detail_urls_with_scroll(
    target_count: int = 1000,
    max_idle_rounds: int = 8,
    sleep_seconds: float = 2.0,
    headless: bool = True,
) -> List[str]:
    driver = create_driver(headless=headless)
    from selenium.webdriver.common.by import By

    detail_urls: Set[str] = set()
    try:
        driver.get(BASE_URL)
        time.sleep(4)
        idle_rounds = 0
        last_count = 0
        while len(detail_urls) < target_count and idle_rounds < max_idle_rounds:
            anchors = driver.find_elements(By.TAG_NAME, "a")
            for anchor in anchors:
                href = anchor.get_attribute("href")
                if href and DETAIL_URL_RE.fullmatch(href):
                    detail_urls.add(href)
            safe_print(f"[SCROLL] collected detail urls = {len(detail_urls)}")
            if len(detail_urls) == last_count:
                idle_rounds += 1
            else:
                idle_rounds = 0
                last_count = len(detail_urls)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(sleep_seconds)
        return sorted(detail_urls)[:target_count]
    finally:
        driver.quit()


def parse_skill_detail(detail_url: str) -> Dict:
    page_html = get_html_with_retry(detail_url, retries=3)
    page_text = strip_html_to_text(page_html)
    match = DETAIL_URL_RE.fullmatch(detail_url)
    if not match:
        raise ValueError(f"Unexpected detail URL format: {detail_url}")
    owner, repo, skill_slug = match.groups()
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, re.I | re.S)
    skill_name = normalize_text(strip_html_to_text(h1_match.group(1))) if h1_match else skill_slug

    description = extract_field_by_label(
        page_text,
        "Summary",
        ["SKILL.md", "Installs", "Weekly Installs", "Repository", "GitHub Stars", "First Seen", "Security Audits", "Installed on"],
    )
    weekly_installs = extract_field_by_label(
        page_text,
        "Installs",
        ["Repository", "GitHub Stars", "First Seen", "Security Audits", "Installed on"],
    ) or extract_field_by_label(
        page_text,
        "Weekly Installs",
        ["Repository", "GitHub Stars", "First Seen", "Security Audits", "Installed on"],
    )
    first_seen = extract_field_by_label(page_text, "First Seen", ["Security Audits", "Installed on"])
    github_stars = extract_field_by_label(page_text, "GitHub Stars", ["First Seen", "Security Audits", "Installed on"])
    skill_md_sections = extract_skill_markdown_sections(page_html)
    block_skill_md = extract_skill_md_from_html_block(page_html)
    if block_skill_md.get("skill_md") and len(block_skill_md["skill_md"]) > len(skill_md_sections["skill_md"]):
        skill_md_sections["skill_md_html"] = block_skill_md["skill_md_html"]
        skill_md_sections["skill_md_raw_text"] = block_skill_md["skill_md_raw_text"]
        skill_md_sections["skill_md"] = block_skill_md["skill_md"]
        skill_md_sections["skill_md_preview"] = block_skill_md["skill_md"]
        skill_md_sections["skill_md_rest"] = ""
        skill_md_sections["skill_md_source"] = block_skill_md["skill_md_source"]
    repo_url = find_repo_url(page_html, owner, repo)
    category = infer_category(skill_name, repo, description or skill_md_sections["skill_md"])
    skill_id = hashlib.md5(detail_url.encode("utf-8")).hexdigest()[:12]

    return {
        "skill_id": skill_id,
        "skill_name": skill_name,
        "owner": owner,
        "repo": repo,
        "description": description,
        "skill_md_html": skill_md_sections["skill_md_html"],
        "skill_md_raw_text": skill_md_sections["skill_md_raw_text"],
        "skill_md": skill_md_sections["skill_md"],
        "skill_md_preview": skill_md_sections["skill_md_preview"],
        "skill_md_rest": skill_md_sections["skill_md_rest"],
        "skill_md_source": skill_md_sections["skill_md_source"],
        "weekly_installs": clean_metric_field(weekly_installs, "Weekly Installs"),
        "category": category,
        "detail_url": detail_url,
        "repo_url": repo_url,
        "first_seen": first_seen,
        "github_stars": clean_metric_field(github_stars, "GitHub Stars"),
        "weekly_installs_num": parse_compact_number(weekly_installs),
        "github_stars_num": parse_compact_number(github_stars),
    }


def is_record_incomplete(record: Dict) -> bool:
    if not record.get("description"):
        return True
    if not (record.get("skill_md") or record.get("skill_md_text_path")):
        return True
    if not record.get("category"):
        return True
    if not record.get("repo_url"):
        return True
    if record.get("weekly_installs_num") is None:
        return True
    if record.get("github_stars_num") is None:
        return True
    return False


def merge_record_fields(existing: Dict, refreshed: Dict) -> Dict:
    merged = dict(existing)
    for key, value in refreshed.items():
        if value not in (None, ""):
            merged[key] = value
    return normalize_record(merged)


def deduplicate_records(records: List[Dict]) -> List[Dict]:
    mapping = {}
    for record in records:
        if record.get("detail_url"):
            mapping[record["detail_url"]] = record
    return list(mapping.values())


def normalize_existing_outputs() -> Dict[str, int]:
    normalized_data_count = 0
    normalized_checkpoint_count = 0
    if Path(OUTPUT_JSON).exists():
        with open(OUTPUT_JSON, "r", encoding="utf-8") as file:
            records = json.load(file)
        normalized_records = normalize_records(records)
        save_outputs(normalized_records)
        normalized_data_count = len(normalized_records)
    if Path(CHECKPOINT_FILE).exists():
        checkpoint = load_checkpoint()
        checkpoint_records = checkpoint.get("records", [])
        checkpoint["records"] = normalize_records(checkpoint_records)
        save_checkpoint(checkpoint)
        normalized_checkpoint_count = len(checkpoint["records"])
    return {
        "normalized_data_count": normalized_data_count,
        "normalized_checkpoint_count": normalized_checkpoint_count,
    }


def migrate_skill_md_storage() -> Dict[str, int]:
    migrated_data_count = 0
    migrated_checkpoint_count = 0

    if Path(OUTPUT_JSON).exists():
        with open(OUTPUT_JSON, "r", encoding="utf-8") as file:
            records = json.load(file)
        save_outputs(records)
        migrated_data_count = len(records)

    if Path(CHECKPOINT_FILE).exists():
        checkpoint = load_checkpoint()
        checkpoint_records = checkpoint.get("records", [])
        checkpoint["records"] = [externalize_skill_md_assets(record) for record in normalize_records(checkpoint_records)]
        save_checkpoint(checkpoint)
        migrated_checkpoint_count = len(checkpoint["records"])

    return {
        "migrated_data_count": migrated_data_count,
        "migrated_checkpoint_count": migrated_checkpoint_count,
    }


def _persist_records(
    original_records: List[Dict],
    original_checkpoint_records: List[Dict],
    records_by_url: Dict[str, Dict],
    checkpoint_by_url: Dict[str, Dict],
    checkpoint: Dict,
    failed_urls: Set[str],
) -> tuple[List[Dict], List[Dict]]:
    updated_records = [
        records_by_url.get(record.get("detail_url"), dict(record))
        for record in original_records
    ]
    updated_checkpoint_records = [
        checkpoint_by_url.get(record.get("detail_url"), dict(record))
        for record in original_checkpoint_records
    ]
    updated_records = deduplicate_records(updated_records)
    updated_checkpoint_records = deduplicate_records(updated_checkpoint_records)
    failed_urls.difference_update(
        record.get("detail_url")
        for record in updated_checkpoint_records
        if record.get("detail_url")
    )
    save_outputs(updated_records)
    checkpoint["records"] = updated_checkpoint_records
    checkpoint["failed_urls"] = sorted(failed_urls)
    save_checkpoint(checkpoint)
    return updated_records, updated_checkpoint_records


def backfill_skill_md_records(
    limit: Optional[int] = None,
    sleep_seconds: float = 0.0,
    flush_every: int = 20,
) -> Dict[str, int]:
    if not Path(OUTPUT_JSON).exists():
        return {
            "candidate_count": 0,
            "refreshed_count": 0,
            "failed_count": 0,
            "remaining_missing_skill_md_count": 0,
        }

    with open(OUTPUT_JSON, "r", encoding="utf-8") as file:
        records = json.load(file)

    checkpoint = load_checkpoint()
    checkpoint_records = checkpoint.get("records", [])
    candidates = [record for record in records if not record.get("skill_md")]
    if limit is not None:
        candidates = candidates[:limit]

    records_by_url = {
        record["detail_url"]: dict(record)
        for record in records
        if record.get("detail_url")
    }
    checkpoint_by_url = {
        record["detail_url"]: dict(record)
        for record in checkpoint_records
        if record.get("detail_url")
    }
    failed_urls = set(checkpoint.get("failed_urls", []))

    refreshed_count = 0
    failed_count = 0

    for index, record in enumerate(candidates, start=1):
        detail_url = record.get("detail_url")
        if not detail_url:
            continue
        try:
            refreshed = parse_skill_detail(detail_url)
            records_by_url[detail_url] = merge_record_fields(record, refreshed)
            checkpoint_existing = checkpoint_by_url.get(detail_url, record)
            checkpoint_by_url[detail_url] = merge_record_fields(checkpoint_existing, refreshed)
            failed_urls.discard(detail_url)
            refreshed_count += 1
            if refreshed_count <= 5 or refreshed_count % 25 == 0:
                safe_print(
                    f"[BACKFILL] {refreshed_count}/{len(candidates)} "
                    f"{refreshed.get('skill_name','')} | skill_md_len={len(refreshed.get('skill_md') or '')}"
                )
        except Exception as exc:
            safe_print(f"[BACKFILL ERROR] {detail_url} -> {exc}")
            failed_urls.add(detail_url)
            failed_count += 1

        if index % max(flush_every, 1) == 0:
            _persist_records(
                original_records=records,
                original_checkpoint_records=checkpoint_records,
                records_by_url=records_by_url,
                checkpoint_by_url=checkpoint_by_url,
                checkpoint=checkpoint,
                failed_urls=failed_urls,
            )

        if sleep_seconds:
            time.sleep(sleep_seconds)

    updated_records, _ = _persist_records(
        original_records=records,
        original_checkpoint_records=checkpoint_records,
        records_by_url=records_by_url,
        checkpoint_by_url=checkpoint_by_url,
        checkpoint=checkpoint,
        failed_urls=failed_urls,
    )

    remaining_missing_skill_md_count = sum(
        1 for record in updated_records if not record.get("skill_md")
    )
    return {
        "candidate_count": len(candidates),
        "refreshed_count": refreshed_count,
        "failed_count": failed_count,
        "remaining_missing_skill_md_count": remaining_missing_skill_md_count,
    }


def refresh_incomplete_records(limit: Optional[int] = None, sleep_seconds: float = 0.5) -> Dict[str, int]:
    if not Path(OUTPUT_JSON).exists():
        return {
            "candidate_count": 0,
            "refreshed_count": 0,
            "failed_count": 0,
            "remaining_incomplete_count": 0,
        }
    with open(OUTPUT_JSON, "r", encoding="utf-8") as file:
        records = json.load(file)
    checkpoint = load_checkpoint()
    checkpoint_records = checkpoint.get("records", [])
    candidates = [record for record in records if is_record_incomplete(record)]
    if limit is not None:
        candidates = candidates[:limit]

    records_by_url = {
        record["detail_url"]: dict(record)
        for record in records
        if record.get("detail_url")
    }
    checkpoint_by_url = {
        record["detail_url"]: dict(record)
        for record in checkpoint_records
        if record.get("detail_url")
    }
    failed_urls = set(checkpoint.get("failed_urls", []))
    refreshed_count = 0
    failed_count = 0

    for record in candidates:
        detail_url = record.get("detail_url")
        if not detail_url:
            continue
        try:
            refreshed = parse_skill_detail(detail_url)
            records_by_url[detail_url] = merge_record_fields(record, refreshed)
            checkpoint_existing = checkpoint_by_url.get(detail_url, record)
            checkpoint_by_url[detail_url] = merge_record_fields(checkpoint_existing, refreshed)
            failed_urls.discard(detail_url)
            refreshed_count += 1
        except Exception as exc:
            safe_print(f"[REFRESH ERROR] {detail_url} -> {exc}")
            failed_urls.add(detail_url)
            failed_count += 1
        time.sleep(sleep_seconds)

    updated_records = [
        records_by_url.get(record.get("detail_url"), dict(record))
        for record in records
    ]
    updated_checkpoint_records = [
        checkpoint_by_url.get(record.get("detail_url"), dict(record))
        for record in checkpoint_records
    ]
    updated_records = deduplicate_records(updated_records)
    updated_checkpoint_records = deduplicate_records(updated_checkpoint_records)
    failed_urls.difference_update(
        record.get("detail_url")
        for record in updated_checkpoint_records
        if record.get("detail_url")
    )
    save_outputs(updated_records)
    checkpoint["records"] = updated_checkpoint_records
    checkpoint["failed_urls"] = sorted(failed_urls)
    save_checkpoint(checkpoint)
    remaining_incomplete_count = sum(1 for record in updated_records if is_record_incomplete(record))
    return {
        "candidate_count": len(candidates),
        "refreshed_count": refreshed_count,
        "failed_count": failed_count,
        "remaining_incomplete_count": remaining_incomplete_count,
    }


def sync_dataset(
    target_count: int = 1000,
    sleep_seconds: float = 0.0,
    headless: bool = True,
    backfill_flush_every: int = 20,
) -> Dict[str, object]:
    backfill_summary = backfill_skill_md_records(
        limit=None,
        sleep_seconds=sleep_seconds,
        flush_every=backfill_flush_every,
    )

    dataset_count = 0
    if Path(OUTPUT_JSON).exists():
        with open(OUTPUT_JSON, "r", encoding="utf-8") as file:
            dataset_count = len(json.load(file))

    crawl_summary = {
        "attempted": dataset_count < target_count,
        "target_count": target_count,
        "dataset_count_before_crawl": dataset_count,
    }
    if dataset_count < target_count:
        crawl_skills(target_count=target_count, sleep_seconds=sleep_seconds or 0.2, headless=headless)

    return {
        "backfill_skill_md": backfill_summary,
        "crawl": crawl_summary,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shared crawler for skills dataset")
    parser.add_argument("--target-count", type=int, default=1000, help="Desired dataset size")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="Delay between requests")
    parser.add_argument("--headless", action="store_true", help="Use headless browser when crawling new URLs")
    parser.add_argument("--flush-every", type=int, default=20, help="Persist progress every N refreshed records")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["sync", "backfill-skill-md", "crawl", "normalize-data", "refresh-data", "migrate-skill-md-storage"],
        default="sync",
        help="Operation to run",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional limit for refresh/backfill commands")
    return parser


def crawl_skills(
    target_count: int = 1000,
    sleep_seconds: float = 0.8,
    headless: bool = True,
) -> None:
    checkpoint = load_checkpoint()
    detail_urls = set(checkpoint.get("detail_urls", []))
    records = checkpoint.get("records", [])
    failed_urls = set(checkpoint.get("failed_urls", []))
    done_urls = {record["detail_url"] for record in records if "detail_url" in record}

    if len(detail_urls) < target_count:
        safe_print("[INFO] collecting detail urls from homepage by scrolling...")
        new_urls = collect_detail_urls_with_scroll(
            target_count=target_count,
            headless=headless,
            sleep_seconds=2.0,
        )
        detail_urls.update(new_urls)
        checkpoint["detail_urls"] = sorted(detail_urls)
        checkpoint["records"] = records
        checkpoint["failed_urls"] = sorted(failed_urls)
        save_checkpoint(checkpoint)

    detail_url_list = sorted(detail_urls)[:target_count]
    tracked_urls = set(detail_url_list)
    tracked_done_urls = {url for url in done_urls if url in tracked_urls}
    safe_print(f"[INFO] total collected detail urls: {len(detail_url_list)}")
    safe_print(f"[INFO] already done: {len(tracked_done_urls)}")

    for detail_url in detail_url_list:
        if detail_url in done_urls:
            continue
        try:
            item = parse_skill_detail(detail_url)
            records.append(item)
            records = deduplicate_records(records)
            done_urls.add(detail_url)
            if detail_url in tracked_urls:
                tracked_done_urls.add(detail_url)
            checkpoint["detail_urls"] = detail_url_list
            checkpoint["records"] = records
            checkpoint["failed_urls"] = sorted(failed_urls - {detail_url})
            save_checkpoint(checkpoint)
            save_outputs(records)
            safe_print(
                f"[{len(tracked_done_urls)}/{len(detail_url_list)}] "
                f"{item['skill_name']} | installs={item['weekly_installs']} | "
                f"stars={item['github_stars']} | category={item['category']} | "
                f"skill_md={'yes' if item.get('skill_md') else 'no'}"
            )
        except Exception as exc:
            safe_print(f"[DETAIL ERROR] {detail_url} -> {exc}")
            failed_urls.add(detail_url)
            checkpoint["detail_urls"] = detail_url_list
            checkpoint["records"] = records
            checkpoint["failed_urls"] = sorted(failed_urls)
            save_checkpoint(checkpoint)
        time.sleep(sleep_seconds)

    if failed_urls:
        safe_print(f"[INFO] retry failed urls: {len(failed_urls)}")
        for detail_url in sorted(failed_urls):
            if detail_url in done_urls:
                continue
            try:
                item = parse_skill_detail(detail_url)
                records.append(item)
                records = deduplicate_records(records)
                done_urls.add(detail_url)
                failed_urls.discard(detail_url)
                checkpoint["detail_urls"] = detail_url_list
                checkpoint["records"] = records
                checkpoint["failed_urls"] = sorted(failed_urls)
                save_checkpoint(checkpoint)
                save_outputs(records)
                safe_print(f"[RECOVERED] {item['skill_name']}")
            except Exception as exc:
                safe_print(f"[FINAL FAIL] {detail_url} -> {exc}")
            time.sleep(sleep_seconds)

    records = deduplicate_records(records)
    done_urls = {record["detail_url"] for record in records if "detail_url" in record}
    failed_urls.difference_update(done_urls)
    save_outputs(records)
    checkpoint["detail_urls"] = detail_url_list
    checkpoint["records"] = records
    checkpoint["failed_urls"] = sorted(failed_urls)
    save_checkpoint(checkpoint)
    safe_print(f"[DONE] records saved: {len(records)}")
    safe_print(f"[DONE] failed urls left: {len(failed_urls)}")
    safe_print(f"[DONE] output files: {OUTPUT_JSON}, {OUTPUT_CSV}, {CHECKPOINT_FILE}")


if __name__ == "__main__":
    args = _build_parser().parse_args()

    if args.command == "sync":
        print(
            json.dumps(
                sync_dataset(
                    target_count=args.target_count,
                    sleep_seconds=args.sleep_seconds,
                    headless=args.headless,
                    backfill_flush_every=args.flush_every,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "backfill-skill-md":
        print(
            json.dumps(
                backfill_skill_md_records(
                    limit=args.limit,
                    sleep_seconds=args.sleep_seconds,
                    flush_every=args.flush_every,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "crawl":
        crawl_skills(
            target_count=args.target_count,
            sleep_seconds=args.sleep_seconds or 0.2,
            headless=args.headless,
        )
    elif args.command == "normalize-data":
        print(json.dumps(normalize_existing_outputs(), ensure_ascii=False, indent=2))
    elif args.command == "migrate-skill-md-storage":
        print(json.dumps(migrate_skill_md_storage(), ensure_ascii=False, indent=2))
    elif args.command == "refresh-data":
        print(
            json.dumps(
                refresh_incomplete_records(limit=args.limit, sleep_seconds=args.sleep_seconds or 0.2),
                ensure_ascii=False,
                indent=2,
            )
        )
