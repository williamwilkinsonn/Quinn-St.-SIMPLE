from __future__ import annotations

import csv
import io
import json
import os
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"
MAX_SEARCH_QUERIES = 12
MAX_RESULTS_PER_QUERY = 20
REQUEST_TIMEOUT = 15
EMAIL_REGEX = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")
CONTACT_LINK_HINTS = (
    "contact",
    "about",
    "wholesale",
    "stockist",
    "retailer",
    "store",
    "support",
)
DEFAULT_TERMS = [
    "baby boutique",
    "children's boutique",
    "baby clothing store",
    "children's clothing store",
    "newborn boutique",
    "gift boutique",
    "maternity boutique",
    "toy boutique",
]


def load_env_file() -> None:
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def get_places_api_key() -> str:
    load_env_file()
    return os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()


def get_host_port() -> tuple[str, int]:
    load_env_file()
    # Use 0.0.0.0 to listen on all interfaces (required for Railway)
    host = os.environ.get("QUINN_STREET_HOST", "0.0.0.0").strip() or "0.0.0.0"
    try:
        port = int(os.environ.get("PORT", os.environ.get("QUINN_STREET_PORT", "8035")))
    except ValueError:
        port = 8035
    return host, port


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def normalize_url(url: str) -> str:
    trimmed = (url or "").strip()
    if not trimmed:
        return ""
    if trimmed.startswith(("http://", "https://")):
        return trimmed
    return f"https://{trimmed}"


def clean_email(candidate: str) -> str:
    value = candidate.strip().strip(".,;:()[]{}<>")
    if value.lower().startswith("mailto:"):
        value = value[7:]
    return value.lower()


def same_domain(base_url: str, candidate_url: str) -> bool:
    base_domain = urlparse(base_url).netloc.lower().lstrip("www.")
    candidate_domain = urlparse(candidate_url).netloc.lower().lstrip("www.")
    return bool(base_domain and candidate_domain and base_domain == candidate_domain)


def extract_emails_from_text(text: str) -> list[str]:
    return sorted({clean_email(match) for match in EMAIL_REGEX.findall(text or "")})


def extract_candidate_links(base_url: str, soup: BeautifulSoup) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        label = anchor.get_text(" ", strip=True).lower()
        absolute_url = urljoin(base_url, href)
        if absolute_url in seen:
            continue
        if not same_domain(base_url, absolute_url):
            continue
        joined_text = f"{label} {href.lower()}"
        if any(hint in joined_text for hint in CONTACT_LINK_HINTS):
            links.append(absolute_url)
            seen.add(absolute_url)
        if len(links) >= 4:
            break
    return links


def fetch_page(url: str) -> tuple[str, str]:
    response = requests.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "QuinnStreetLeadGen/1.0 (+https://quinnstreet.example)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        return response.url, ""
    return response.url, response.text


@dataclass
class Lead:
    place_id: str
    name: str
    address: str
    phone: str
    website: str
    maps_url: str
    rating: str
    review_count: str
    primary_type: str
    business_status: str
    matched_queries: list[str]
    email: str = ""
    extra_emails: list[str] | None = None
    contact_page: str = ""
    enrichment_status: str = "not_run"

    def to_dict(self) -> dict[str, Any]:
        return {
            "place_id": self.place_id,
            "name": self.name,
            "address": self.address,
            "phone": self.phone,
            "website": self.website,
            "maps_url": self.maps_url,
            "rating": self.rating,
            "review_count": self.review_count,
            "primary_type": self.primary_type,
            "business_status": self.business_status,
            "matched_queries": self.matched_queries,
            "email": self.email,
            "extra_emails": self.extra_emails or [],
            "contact_page": self.contact_page,
            "enrichment_status": self.enrichment_status,
        }


def build_search_body(query: str, max_results: int) -> dict[str, Any]:
    return {
        "textQuery": query,
        "maxResultCount": max(1, min(max_results, MAX_RESULTS_PER_QUERY)),
    }


def places_search(location: str, search_terms: list[str], max_results: int) -> list[Lead]:
    api_key = get_places_api_key()
    if not api_key:
        raise RuntimeError("Missing GOOGLE_PLACES_API_KEY. Add it to quinn_street_leads/.env or your shell environment.")

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ",".join(
            [
                "places.id",
                "places.displayName",
                "places.formattedAddress",
                "places.websiteUri",
                "places.nationalPhoneNumber",
                "places.googleMapsUri",
                "places.rating",
                "places.userRatingCount",
                "places.primaryTypeDisplayName",
                "places.businessStatus",
            ]
        ),
    }

    leads_by_id: dict[str, Lead] = {}
    session = requests.Session()
    for term in search_terms[:MAX_SEARCH_QUERIES]:
        text_query = f"{term} in {location}"
        response = session.post(
            PLACES_API_URL,
            headers=headers,
            json=build_search_body(text_query, max_results),
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code >= 400:
            detail = response.text[:500]
            raise RuntimeError(f"Google Places search failed for '{term}': {detail}")
        payload = response.json()
        for place in payload.get("places", []):
            place_id = str(place.get("id") or "")
            if not place_id:
                continue
            existing = leads_by_id.get(place_id)
            if existing:
                if term not in existing.matched_queries:
                    existing.matched_queries.append(term)
                continue
            leads_by_id[place_id] = Lead(
                place_id=place_id,
                name=((place.get("displayName") or {}).get("text") or "").strip(),
                address=(place.get("formattedAddress") or "").strip(),
                phone=(place.get("nationalPhoneNumber") or "").strip(),
                website=(place.get("websiteUri") or "").strip(),
                maps_url=(place.get("googleMapsUri") or "").strip(),
                rating=str(place.get("rating") or ""),
                review_count=str(place.get("userRatingCount") or ""),
                primary_type=((place.get("primaryTypeDisplayName") or {}).get("text") or "").strip(),
                business_status=(place.get("businessStatus") or "").strip(),
                matched_queries=[term],
            )

    return sorted(
        leads_by_id.values(),
        key=lambda lead: (
            -(float(lead.rating) if lead.rating else 0.0),
            -(int(lead.review_count) if lead.review_count.isdigit() else 0),
            lead.name.lower(),
        ),
    )


def enrich_lead(lead: dict[str, Any]) -> dict[str, Any]:
    website = normalize_url(str(lead.get("website") or ""))
    if not website:
        lead["enrichment_status"] = "no_website"
        return lead

    emails: list[str] = []
    contact_page = ""
    checked_pages: list[str] = []
    try:
        final_url, html = fetch_page(website)
        checked_pages.append(final_url)
        emails.extend(extract_emails_from_text(html))
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if href.lower().startswith("mailto:"):
                emails.append(clean_email(href))
        candidate_links = extract_candidate_links(final_url, soup)
        for page_url in candidate_links:
            if page_url in checked_pages:
                continue
            checked_pages.append(page_url)
            try:
                _, sub_html = fetch_page(page_url)
            except requests.RequestException:
                continue
            page_emails = extract_emails_from_text(sub_html)
            if page_emails and not contact_page:
                contact_page = page_url
            emails.extend(page_emails)
            if not contact_page and any(hint in page_url.lower() for hint in CONTACT_LINK_HINTS):
                contact_page = page_url
            if emails:
                break
        if not contact_page and candidate_links:
            contact_page = candidate_links[0]
    except requests.RequestException as exc:
        lead["enrichment_status"] = f"fetch_error: {exc.__class__.__name__}"
        return lead

    unique_emails = sorted({email for email in emails if email})
    lead["email"] = unique_emails[0] if unique_emails else ""
    lead["extra_emails"] = unique_emails[1:]
    lead["contact_page"] = contact_page
    lead["enrichment_status"] = "email_found" if unique_emails else "contact_page_found" if contact_page else "no_email_found"
    return lead


def export_csv(leads: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    fieldnames = [
        "name",
        "address",
        "phone",
        "website",
        "email",
        "extra_emails",
        "contact_page",
        "maps_url",
        "rating",
        "review_count",
        "primary_type",
        "business_status",
        "matched_queries",
        "enrichment_status",
        "place_id",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for lead in leads:
        row = dict(lead)
        row["extra_emails"] = ", ".join(row.get("extra_emails") or [])
        row["matched_queries"] = ", ".join(row.get("matched_queries") or [])
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return buffer.getvalue()


class QuinnStreetHandler(BaseHTTPRequestHandler):
    server_version = "QuinnStreetLeadGen/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/config":
            json_response(
                self,
                HTTPStatus.OK,
                {
                    "hasApiKey": bool(get_places_api_key()),
                    "defaultTerms": DEFAULT_TERMS,
                },
            )
            return
        if self.path == "/api/health":
            json_response(self, HTTPStatus.OK, {"ok": True})
            return
        self.serve_static()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/search":
            self.handle_search()
            return
        if self.path == "/api/enrich":
            self.handle_enrich()
            return
        if self.path == "/api/export":
            self.handle_export()
            return
        json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def handle_search(self) -> None:
        try:
            payload = self.read_json_body()
            location = str(payload.get("location") or "").strip()
            if not location:
                raise ValueError("Location is required.")
            requested_terms = payload.get("searchTerms") or DEFAULT_TERMS
            if not isinstance(requested_terms, list):
                raise ValueError("searchTerms must be an array.")
            search_terms = [str(term).strip() for term in requested_terms if str(term).strip()]
            if not search_terms:
                search_terms = list(DEFAULT_TERMS)
            max_results = int(payload.get("maxResults") or 10)
            leads = [lead.to_dict() for lead in places_search(location, search_terms, max_results)]
            json_response(self, HTTPStatus.OK, {"leads": leads, "count": len(leads)})
        except ValueError as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except RuntimeError as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except requests.RequestException as exc:
            json_response(self, HTTPStatus.BAD_GATEWAY, {"error": f"Network error while querying Google Places: {exc}"})

    def handle_enrich(self) -> None:
        try:
            payload = self.read_json_body()
            leads = payload.get("leads")
            if not isinstance(leads, list):
                raise ValueError("leads must be an array.")
            enriched = [enrich_lead(dict(lead)) for lead in leads]
            json_response(self, HTTPStatus.OK, {"leads": enriched, "count": len(enriched)})
        except ValueError as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def handle_export(self) -> None:
        try:
            payload = self.read_json_body()
            leads = payload.get("leads")
            if not isinstance(leads, list):
                raise ValueError("leads must be an array.")
            csv_text = export_csv([dict(lead) for lead in leads])
            body = csv_text.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="quinn_street_leads.csv"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except ValueError as exc:
            json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def serve_static(self) -> None:
        request_path = self.path.split("?", 1)[0]
        if request_path in ("", "/"):
            file_path = STATIC_DIR / "index.html"
        else:
            file_path = (STATIC_DIR / request_path.lstrip("/")).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())):
                json_response(self, HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
                return
        if not file_path.exists() or not file_path.is_file():
            json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        content_type = "text/plain; charset=utf-8"
        if file_path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host, port = get_host_port()
    server = ThreadingHTTPServer((host, port), QuinnStreetHandler)
    print(f"Quinn Street lead generator running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
