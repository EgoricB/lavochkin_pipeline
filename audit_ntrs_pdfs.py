import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
PDF_DIR = ROOT / "data" / "ntrs" / "raw"
OUT_DIR = ROOT / "data" / "ntrs" / "audit"

FIELDS = [
    "file",
    "relative_path",
    "size_bytes",
    "sha256",
    "duplicate_of",
    "pdf_title",
    "pages",
    "pages_checked",
    "pages_with_text",
    "text_chars",
    "page_text_errors",
    "encrypted",
    "status",
    "error",
]


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_pdf(path):
    row = {field: "" for field in FIELDS}
    row.update(
        file=path.name,
        relative_path=str(path.relative_to(ROOT)),
        pages_checked=0,
        pages_with_text=0,
        text_chars=0,
        page_text_errors=0,
        encrypted=False,
    )

    try:
        row["size_bytes"] = path.stat().st_size
        row["sha256"] = file_hash(path)

        with path.open("rb") as stream:
            reader = PdfReader(stream, strict=False)
            row["encrypted"] = reader.is_encrypted

            if reader.is_encrypted and not reader.decrypt(""):
                row["status"] = "password_required"
                return row

            row["pages"] = len(reader.pages)

            try:
                metadata = reader.metadata
                row["pdf_title"] = str(metadata.title or "") if metadata else ""
            except Exception:
                pass

            page_errors = []

            for page_number in range(row["pages"]):
                try:
                    text = reader.pages[page_number].extract_text() or ""
                    chars = len(text.strip())
                    row["pages_checked"] += 1
                    row["text_chars"] += chars
                    if chars:
                        row["pages_with_text"] += 1
                except Exception as exc:
                    row["page_text_errors"] += 1
                    if len(page_errors) < 5:
                        page_errors.append(
                            f"page {page_number + 1}: "
                            f"{type(exc).__name__}: {exc}"
                        )

            if row["pages"] == 0:
                row["status"] = "zero_pages"
            elif row["page_text_errors"]:
                row["status"] = "text_extraction_errors"
            elif row["text_chars"] == 0:
                row["status"] = "no_extractable_text"
            else:
                row["status"] = "text_extracted"

            row["error"] = " | ".join(page_errors)

    except Exception as exc:
        row["status"] = "read_error"
        row["error"] = f"{type(exc).__name__}: {exc}"

    return row


def main():
    if not PDF_DIR.is_dir():
        raise SystemExit(f"PDF folder not found: {PDF_DIR}")

    files = sorted(
        path for path in PDF_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )
    if not files:
        raise SystemExit(f"No PDF files found in: {PDF_DIR}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "pdf_audit.csv"
    summary_path = OUT_DIR / "summary.json"

    counts = Counter()
    seen_hashes = {}
    duplicate_count = 0
    total_bytes = 0
    total_pages = 0
    total_chars = 0

    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()

        for index, path in enumerate(files, 1):
            print(f"[{index}/{len(files)}] Checking: {path.name}", flush=True)
            row = audit_pdf(path)

            digest = row["sha256"]
            if digest:
                if digest in seen_hashes:
                    row["duplicate_of"] = seen_hashes[digest]
                    duplicate_count += 1
                else:
                    seen_hashes[digest] = row["relative_path"]

            counts[row["status"]] += 1
            total_bytes += row["size_bytes"] or 0
            total_pages += row["pages"] or 0
            total_chars += row["text_chars"] or 0

            writer.writerow(row)
            stream.flush()

            print(
                f"  {row['status']} | pages={row['pages']} | "
                f"chars={row['text_chars']}",
                flush=True,
            )

    summary = {
        "pdf_files": len(files),
        "total_bytes": total_bytes,
        "total_pages": total_pages,
        "extracted_text_chars": total_chars,
        "exact_duplicate_files": duplicate_count,
        "statuses": dict(sorted(counts.items())),
        "relevance": "UNREVIEWED",
        "mission_year_filtering": False,
    }

    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nAUDIT COMPLETE")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nCSV: {csv_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
