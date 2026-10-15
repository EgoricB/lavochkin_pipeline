import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "ntrs"
OUT = BASE / "processed"

INTEGER_FIELDS = {
    "size_bytes",
    "pages",
    "pages_checked",
    "pages_with_text",
    "text_chars",
    "page_text_errors",
}


def convert_audit_row(row):
    result = dict(row)

    for field in INTEGER_FIELDS:
        value = result.get(field, "")
        result[field] = int(value) if value != "" else None

    encrypted = result.get("encrypted", "")
    result["encrypted"] = (
        encrypted.lower() == "true" if encrypted != "" else None
    )

    return result


def get_ntrs_id(filename):
    match = re.fullmatch(
        r"(?P<id>\d+)_(?P<index>\d+)\.pdf",
        filename,
        flags=re.IGNORECASE,
    )
    return match.group("id") if match else None


def main():
    candidates = json.loads(
        (BASE / "candidates.json").read_text(encoding="utf-8-sig")
    )

    if not isinstance(candidates, dict):
        raise SystemExit("Expected candidates.json to contain a dictionary.")

    with (BASE / "audit" / "pdf_audit.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        audit_rows = [convert_audit_row(row) for row in csv.DictReader(stream)]

    candidates = {str(key): value for key, value in candidates.items()}
    files_by_id = {}
    unmatched = []

    for row in audit_rows:
        ntrs_id = get_ntrs_id(row["file"])

        if ntrs_id is None or ntrs_id not in candidates:
            unmatched.append({
                "parsed_ntrs_id": ntrs_id,
                "reason": (
                    "filename_pattern_not_recognized"
                    if ntrs_id is None
                    else "candidate_not_found"
                ),
                "audit": row,
            })
            continue

        files_by_id.setdefault(ntrs_id, []).append(row)

    documents = []

    for ntrs_id, candidate in candidates.items():
        record = candidate.get("record") or {}
        files = files_by_id.get(ntrs_id, [])

        document = {
            "ntrs_id": ntrs_id,
            "title": record.get("title"),
            "abstract": record.get("abstract"),
            "document_type": record.get("stiType"),
            "subject_categories": record.get("subjectCategories") or [],
            "search_queries": candidate.get("queries") or [],
            "has_local_pdf": bool(files),
            "local_pdf_count": len(files),
            "files": files,
            "review": {
                "relevance": "UNREVIEWED",
                "missions": [],
                "mission_year_filtering_applied": False,
                "needs_text_review": any(
                    item["status"] != "text_extracted" for item in files
                ),
                "ocr_candidate": any(
                    item["status"] == "no_extractable_text" for item in files
                ),
                "notes": [],
            },
            "source_candidate": candidate,
        }

        documents.append(document)

    matched_files = [
        item
        for document in documents
        for item in document["files"]
    ]

    summary = {
        "candidate_records": len(documents),
        "records_with_local_pdf": sum(
            document["has_local_pdf"] for document in documents
        ),
        "records_without_local_pdf": sum(
            not document["has_local_pdf"] for document in documents
        ),
        "audited_pdf_files": len(audit_rows),
        "matched_pdf_files": len(matched_files),
        "unmatched_pdf_files": len(unmatched),
        "matched_pdf_statuses": dict(sorted(Counter(
            item["status"] for item in matched_files
        ).items())),
    }

    corpus = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "NTRS",
        "inputs": {
            "candidates": "data/ntrs/candidates.json",
            "audit": "data/ntrs/audit/pdf_audit.csv",
        },
        "matching": {
            "method": "numeric NTRS ID from <id>_<index>.pdf filename",
            "semantic_matching_performed": False,
        },
        "summary": summary,
        "documents": documents,
        "unmatched_pdf_files": unmatched,
    }

    OUT.mkdir(parents=True, exist_ok=True)

    corpus_path = OUT / "corpus.json"
    corpus_path.write_text(
        json.dumps(corpus, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    table_path = OUT / "documents.csv"
    fields = [
        "ntrs_id",
        "title",
        "document_type",
        "search_queries",
        "has_local_pdf",
        "local_pdf_count",
        "total_pages",
        "text_chars",
        "pdf_statuses",
        "needs_text_review",
        "ocr_candidate",
        "relevance",
    ]

    with table_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()

        for document in documents:
            files = document["files"]
            writer.writerow({
                "ntrs_id": document["ntrs_id"],
                "title": document["title"],
                "document_type": document["document_type"],
                "search_queries": json.dumps(
                    document["search_queries"], ensure_ascii=False
                ),
                "has_local_pdf": document["has_local_pdf"],
                "local_pdf_count": document["local_pdf_count"],
                "total_pages": (
                    sum(item["pages"] or 0 for item in files)
                    if files else None
                ),
                "text_chars": (
                    sum(item["text_chars"] or 0 for item in files)
                    if files else None
                ),
                "pdf_statuses": "; ".join(
                    sorted({item["status"] for item in files})
                ),
                "needs_text_review": document["review"]["needs_text_review"],
                "ocr_candidate": document["review"]["ocr_candidate"],
                "relevance": document["review"]["relevance"],
            })

    print("CORPUS BUILD COMPLETE")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nJSON: {corpus_path}")
    print(f"CSV: {table_path}")

    if unmatched:
        print("\nWARNING: Some PDFs were not matched. See unmatched_pdf_files.")


if __name__ == "__main__":
    main()
