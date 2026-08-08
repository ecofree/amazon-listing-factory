from __future__ import annotations

import csv
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .io import utc_now
from .paths import FACTORY_ROOT


SCHEMA_VERSION = 1
DEFAULT_SEARCH_TERM_DB = FACTORY_ROOT / "data" / "search_terms.sqlite"

PROJECT_CATEGORY_TO_SEARCH_CATEGORIES = {
    "bed_frame": ("bed",),
    "bed frame": ("bed",),
    "bathroom_cabinet": ("cabinet",),
    "bathroom cabinet": ("cabinet",),
    "medicine_cabinet": ("cabinet",),
    "medicine cabinet": ("cabinet",),
    "artificial_tree": ("tree", "plants"),
    "artificial tree": ("tree", "plants"),
}

COLOR_WORDS = {
    "black",
    "blue",
    "brown",
    "gray",
    "grey",
    "green",
    "natural",
    "pink",
    "red",
    "walnut",
    "white",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

CATEGORY_EXCLUDED_TERMS = {
    "bed": {"dog", "cat", "pet", "sofa", "air", "flower"},
    "cabinet": {"lighting", "light", "hinge", "knob", "paint"},
    "tree": {"cat", "tea", "christmas", "storage", "saddle", "oil", "planter"},
    "plants": {"cat", "tea", "christmas", "storage", "saddle", "oil", "planter"},
}

BED_SIZE_TOKENS = {"twin", "full", "queen", "king", "california"}
REFERENCE_TITLE_CORE_STARTERS = {
    "adjustable",
    "arched",
    "artificial",
    "bathroom",
    "bed",
    "bunk",
    "cabinet",
    "faux",
    "floor",
    "full",
    "king",
    "loft",
    "low",
    "medicine",
    "metal",
    "narrow",
    "olive",
    "platform",
    "queen",
    "storage",
    "tall",
    "twin",
    "wall",
    "wood",
    "wooden",
}
REFERENCE_TITLE_BLOCKED_PATTERNS = (
    re.compile(r"\bnon[- ]?toxic\b", re.I),
    re.compile(r"\bbest\b", re.I),
    re.compile(r"\bpremium\s+quality\b", re.I),
    re.compile(r"\bperfect\b", re.I),
    re.compile(r"\bfree\s+shipping\b", re.I),
)


@dataclass(frozen=True)
class SearchTermIngestSummary:
    db_path: str
    files: int
    rows_seen: int
    rows_imported: int
    clicked_products_imported: int
    categories: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "db_path": self.db_path,
            "files": self.files,
            "rows_seen": self.rows_seen,
            "rows_imported": self.rows_imported,
            "clicked_products_imported": self.clicked_products_imported,
            "categories": self.categories,
        }


def default_search_term_db(env: dict[str, str] | None = None) -> Path:
    values = env or {}
    raw = values.get("AMAZON_FACTORY_SEARCH_TERMS_DB") or values.get("COPY_SEARCH_TERMS_DB") or ""
    if raw:
        path = Path(raw)
        return path if path.is_absolute() else FACTORY_ROOT / path
    return DEFAULT_SEARCH_TERM_DB


def init_search_term_db(db_path: str | Path | None = None) -> Path:
    path = Path(db_path) if db_path else DEFAULT_SEARCH_TERM_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_terms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                reporting_range TEXT NOT NULL DEFAULT '',
                reporting_year TEXT NOT NULL DEFAULT '',
                reporting_quarter TEXT NOT NULL DEFAULT '',
                reporting_date TEXT NOT NULL DEFAULT '',
                search_frequency_rank INTEGER NOT NULL DEFAULT 0,
                search_term TEXT NOT NULL,
                search_term_norm TEXT NOT NULL,
                top_brand_1 TEXT NOT NULL DEFAULT '',
                top_brand_2 TEXT NOT NULL DEFAULT '',
                top_brand_3 TEXT NOT NULL DEFAULT '',
                top_category_1 TEXT NOT NULL DEFAULT '',
                top_category_2 TEXT NOT NULL DEFAULT '',
                top_category_3 TEXT NOT NULL DEFAULT '',
                import_source TEXT NOT NULL DEFAULT '',
                imported_at TEXT NOT NULL DEFAULT '',
                UNIQUE(category, reporting_date, search_term_norm)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clicked_products (
                search_term_id INTEGER NOT NULL,
                product_rank INTEGER NOT NULL,
                asin TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                click_share REAL NOT NULL DEFAULT 0,
                conversion_share REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(search_term_id, product_rank),
                FOREIGN KEY(search_term_id) REFERENCES search_terms(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_search_terms_category_rank ON search_terms(category, search_frequency_rank)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_search_terms_norm ON search_terms(search_term_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clicked_products_term ON clicked_products(search_term_id)")
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        conn.commit()
    return path


def ingest_search_term_csvs(
    paths: Iterable[str | Path],
    *,
    db_path: str | Path | None = None,
    category: str = "",
) -> SearchTermIngestSummary:
    expanded = _expand_csv_paths(paths)
    db = init_search_term_db(db_path)
    files = 0
    rows_seen = 0
    rows_imported = 0
    clicked_products_imported = 0
    categories: dict[str, int] = {}
    imported_at = utc_now()
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for csv_path in expanded:
            files += 1
            inferred_category = _normalize_search_category(category or _infer_category_from_filename(csv_path))
            if not inferred_category:
                inferred_category = "unknown"
            metadata, rows = _read_search_term_csv(csv_path)
            for row in rows:
                rows_seen += 1
                term = _clean(row.get("Search Term"))
                if not term:
                    continue
                rank = _coerce_int(row.get("Search Frequency Rank"))
                reporting_date = _clean(row.get("Reporting Date")) or _metadata_value(metadata, "Reporting Date")
                term_norm = normalize_search_term(term)
                term_id = _upsert_search_term(
                    conn,
                    category=inferred_category,
                    reporting_range=_metadata_value(metadata, "Reporting Range"),
                    reporting_year=_metadata_value(metadata, "Select year"),
                    reporting_quarter=_metadata_value(metadata, "Select quarter"),
                    reporting_date=reporting_date,
                    search_frequency_rank=rank,
                    search_term=term,
                    search_term_norm=term_norm,
                    top_brand_1=_clean(row.get("Top Clicked Brand #1")),
                    top_brand_2=_clean(row.get("Top Clicked Brands #2")),
                    top_brand_3=_clean(row.get("Top Clicked Brands #3")),
                    top_category_1=_clean(row.get("Top Clicked Category #1")),
                    top_category_2=_clean(row.get("Top Clicked Category #2")),
                    top_category_3=_clean(row.get("Top Clicked Category #3")),
                    import_source=str(csv_path),
                    imported_at=imported_at,
                )
                conn.execute("DELETE FROM clicked_products WHERE search_term_id = ?", (term_id,))
                for product_rank in (1, 2, 3):
                    title = _clean(row.get(f"Top Clicked Product #{product_rank}: Product Title"))
                    asin = _clean(row.get(f"Top Clicked Product #{product_rank}: ASIN"))
                    if not title and not asin:
                        continue
                    conn.execute(
                        """
                        INSERT INTO clicked_products(search_term_id, product_rank, asin, title, click_share, conversion_share)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            term_id,
                            product_rank,
                            asin,
                            title,
                            _coerce_float(row.get(f"Top Clicked Product #{product_rank}: Click Share")),
                            _coerce_float(row.get(f"Top Clicked Product #{product_rank}: Conversion Share")),
                        ),
                    )
                    clicked_products_imported += 1
                rows_imported += 1
                categories[inferred_category] = categories.get(inferred_category, 0) + 1
        conn.commit()
    return SearchTermIngestSummary(
        db_path=str(db),
        files=files,
        rows_seen=rows_seen,
        rows_imported=rows_imported,
        clicked_products_imported=clicked_products_imported,
        categories=categories,
    )


def title_reference_context(
    *,
    category: str,
    source_title: str,
    product_specific: dict[str, Any] | None,
    env: dict[str, str] | None = None,
    db_path: str | Path | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    values = env or {}
    enabled = str(values.get("AMAZON_FACTORY_SEARCH_TERMS_ENABLED") or values.get("COPY_SEARCH_TERMS_ENABLED") or "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return {}
    db = Path(db_path) if db_path else default_search_term_db(values)
    if not db.exists():
        return {}
    project_category = _normalize_project_category(category)
    search_categories = PROJECT_CATEGORY_TO_SEARCH_CATEGORIES.get(project_category, (_normalize_search_category(category),))
    references = search_title_references(
        db_path=db,
        search_categories=search_categories,
        source_title=source_title,
        product_specific=product_specific or {},
        limit=_coerce_context_limit(values, limit),
    )
    if not references:
        return {}
    return {
        "source": "local_search_terms_db",
        "db_path": str(db),
        "search_categories": list(search_categories),
        "usage_rules": [
            "Use these rows as market structure references only.",
            "Do not copy competitor titles or competitor brand names.",
            "Use a search term only when it is supported by the source title, bullets, or known product facts.",
            "Prefer hard parameters and blocker terms over generic scene words when title length is limited.",
            "Do not add color to the title for normal variation families; Amazon variation fields carry color.",
        ],
        "references": references,
    }


def search_title_references(
    *,
    db_path: str | Path,
    search_categories: Iterable[str],
    source_title: str,
    product_specific: dict[str, Any],
    limit: int = 6,
) -> list[dict[str, Any]]:
    db = Path(db_path)
    product_text = " ".join([str(source_title or ""), _flatten_product_specific(product_specific)])
    product_tokens = _tokenize(product_text)
    if not product_tokens:
        return []
    categories = [_normalize_search_category(item) for item in search_categories if str(item or "").strip()]
    categories = [item for item in categories if item]
    if not categories:
        return []
    placeholders = ",".join("?" for _ in categories)
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        term_rows = conn.execute(
            f"""
            SELECT *
            FROM search_terms
            WHERE category IN ({placeholders})
            ORDER BY reporting_date DESC, search_frequency_rank ASC
            """,
            categories,
        ).fetchall()
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in term_rows:
            term = str(row["search_term"] or "")
            term_tokens = _tokenize(term)
            if not term_tokens:
                continue
            if _excluded_search_term(str(row["category"] or ""), term_tokens):
                continue
            if _brand_search_term(row, term_tokens):
                continue
            if _entity_conflict(str(row["category"] or ""), product_tokens, term_tokens):
                continue
            overlap = len(term_tokens & product_tokens)
            exact = term.lower() in product_text.lower()
            number_match = bool({token for token in term_tokens if any(ch.isdigit() for ch in token)} & product_tokens)
            if overlap <= 0 and not exact and not number_match:
                continue
            rank = int(row["search_frequency_rank"] or 0)
            rank_score = 1000.0 / max(rank, 1) if rank > 0 else 0.0
            score = overlap * 12.0 + (25.0 if exact else 0.0) + (10.0 if number_match else 0.0) + rank_score
            scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], int(item[1]["search_frequency_rank"] or 999999)))
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for score, row in scored:
            norm = str(row["search_term_norm"] or "")
            if norm in seen:
                continue
            seen.add(norm)
            clicked = conn.execute(
                """
                SELECT product_rank, asin, title, click_share, conversion_share
                FROM clicked_products
                WHERE search_term_id = ?
                ORDER BY product_rank
                """,
                (row["id"],),
            ).fetchall()
            brands = [str(row[f"top_brand_{idx}"] or "") for idx in (1, 2, 3)]
            out.append(
                {
                    "search_term": str(row["search_term"] or ""),
                    "search_frequency_rank": int(row["search_frequency_rank"] or 0),
                    "reporting_date": str(row["reporting_date"] or ""),
                    "relevance_score": round(score, 3),
                    "top_clicked_brands": [brand for brand in brands if brand],
                    "top_clicked_titles": [
                        {
                            "rank": int(item["product_rank"] or 0),
                            "asin": str(item["asin"] or ""),
                            "reference_title": _sanitize_reference_title(str(item["title"] or ""), brands),
                            "click_share": float(item["click_share"] or 0),
                            "conversion_share": float(item["conversion_share"] or 0),
                        }
                        for item in clicked[:3]
                        if str(item["title"] or "").strip()
                    ],
                }
            )
            if len(out) >= max(1, limit):
                break
    return out


def normalize_search_term(value: Any) -> str:
    return " ".join(_tokenize(str(value or "")))


def _upsert_search_term(conn: sqlite3.Connection, **values: Any) -> int:
    existing = conn.execute(
        """
        SELECT id
        FROM search_terms
        WHERE category = ? AND reporting_date = ? AND search_term_norm = ?
        """,
        (values["category"], values["reporting_date"], values["search_term_norm"]),
    ).fetchone()
    columns = [
        "category",
        "reporting_range",
        "reporting_year",
        "reporting_quarter",
        "reporting_date",
        "search_frequency_rank",
        "search_term",
        "search_term_norm",
        "top_brand_1",
        "top_brand_2",
        "top_brand_3",
        "top_category_1",
        "top_category_2",
        "top_category_3",
        "import_source",
        "imported_at",
    ]
    if existing:
        assignments = ", ".join(f"{column} = ?" for column in columns)
        conn.execute(
            f"UPDATE search_terms SET {assignments} WHERE id = ?",
            [values[column] for column in columns] + [int(existing[0])],
        )
        return int(existing[0])
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO search_terms({', '.join(columns)}) VALUES ({placeholders})",
        [values[column] for column in columns],
    )
    return int(cur.lastrowid)


def _read_search_term_csv(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        first_line = fh.readline()
        metadata = _parse_metadata_line(first_line)
        reader = csv.DictReader(fh)
        rows = [dict(row) for row in reader if any(str(value or "").strip() for value in row.values())]
    return metadata, rows


def _parse_metadata_line(line: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in re.findall(r'([^=,\[]+)=\["([^"]*)"\]', str(line or "")):
        metadata[key.strip()] = value.strip()
    return metadata


def _metadata_value(metadata: dict[str, str], key: str) -> str:
    return str(metadata.get(key) or "").strip()


def _expand_csv_paths(paths: Iterable[str | Path]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(sorted(path.glob("*.csv")))
        elif path.exists():
            out.append(path)
    return out


def _infer_category_from_filename(path: Path) -> str:
    name = path.stem.lower()
    for category in ("cabinet", "plants", "tree", "bed"):
        if re.search(rf"(?:^|[-_]){re.escape(category)}(?:$|[-_])", name):
            return category
    return ""


def _normalize_search_category(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    aliases = {
        "bed_frame": "bed",
        "bathroom_cabinet": "cabinet",
        "medicine_cabinet": "cabinet",
        "artificial_tree": "tree",
        "plant": "plants",
    }
    return aliases.get(text, text)


def _normalize_project_category(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _coerce_int(value: Any) -> int:
    try:
        return int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float:
    try:
        return float(str(value or "").replace("%", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _coerce_context_limit(values: dict[str, str], default: int) -> int:
    raw = values.get("AMAZON_FACTORY_SEARCH_TERMS_LIMIT") or values.get("COPY_SEARCH_TERMS_LIMIT")
    try:
        return max(1, min(20, int(float(raw)))) if raw is not None else default
    except (TypeError, ValueError):
        return default


def _tokenize(value: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)?", str(value or "").lower()):
        token = token.strip("-/")
        if not token or token in STOPWORDS or token in COLOR_WORDS:
            continue
        tokens.add(token)
    return tokens


def _flatten_product_specific(value: Any, *, depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(value, dict):
        parts: list[str] = []
        for key, nested in value.items():
            key_text = str(key or "")
            if re.search(r"(color|colour|brand|manufacturer|seller|asin|sku|review|rating|rank)", key_text, re.I):
                continue
            parts.append(key_text.replace("_", " "))
            parts.append(_flatten_product_specific(nested, depth=depth + 1))
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        return " ".join(_flatten_product_specific(item, depth=depth + 1) for item in value[:30])
    return str(value or "")


def _excluded_search_term(category: str, term_tokens: set[str]) -> bool:
    excluded = CATEGORY_EXCLUDED_TERMS.get(category, set())
    if category in {"tree", "plants"} and {"pot", "artificial", "tree"} <= term_tokens:
        return True
    return bool(term_tokens & excluded)


def _brand_search_term(row: sqlite3.Row, term_tokens: set[str]) -> bool:
    if not term_tokens:
        return False
    for index in (1, 2, 3):
        brand_tokens = _tokenize(str(row[f"top_brand_{index}"] or ""))
        if not brand_tokens:
            continue
        if term_tokens & brand_tokens:
            return True
    return False


def _entity_conflict(category: str, product_tokens: set[str], term_tokens: set[str]) -> bool:
    if category == "bed":
        product_sizes = product_tokens & BED_SIZE_TOKENS
        term_sizes = term_tokens & BED_SIZE_TOKENS
        if term_sizes and product_sizes and not term_sizes <= product_sizes:
            return True
        if "bunk" in product_tokens and "bunk" not in term_tokens and "loft" not in term_tokens:
            return True
        if "loft" in product_tokens and "loft" not in term_tokens and "bunk" not in term_tokens:
            return True
    return False


def _sanitize_reference_title(title: str, brands: list[str]) -> str:
    out = _clean(title)
    for brand in sorted({item for item in brands if item}, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(brand)}\b", "", out, flags=re.I)
    out = _strip_leading_reference_brand(out)
    for pattern in REFERENCE_TITLE_BLOCKED_PATTERNS:
        out = pattern.sub("", out)
    out = re.sub(r"\s+", " ", out).strip(" ,;-")
    return out


def _strip_leading_reference_brand(title: str) -> str:
    words = str(title or "").strip().split()
    if len(words) < 3:
        return str(title or "").strip()
    first = re.sub(r"[^A-Za-z0-9]+", "", words[0]).lower()
    if first and first not in REFERENCE_TITLE_CORE_STARTERS and not any(ch.isdigit() for ch in first):
        return " ".join(words[1:]).strip(" ,;-")
    return str(title or "").strip()
