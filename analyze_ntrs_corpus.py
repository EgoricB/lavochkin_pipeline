import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "data" / "ntrs"
OUT = BASE / "analytics"


def write_csv(name, rows, fields):
    with (OUT / name).open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def page_bucket(pages):
    if pages is None:
        return "unknown"
    if pages == 0:
        return "0"
    if pages <= 5:
        return "1-5"
    if pages <= 20:
        return "6-20"
    if pages <= 50:
        return "21-50"
    if pages <= 100:
        return "51-100"
    if pages <= 300:
        return "101-300"
    return "301+"


def main():
    corpus = json.loads(
        (BASE / "processed" / "corpus.json").read_text(encoding="utf-8")
    )
    documents = corpus["documents"]
    OUT.mkdir(parents=True, exist_ok=True)

    types_all = Counter()
    types_local = Counter()
    queries_all = Counter()
    queries_local = Counter()
    query_count_distribution = Counter()
    query_sets = {}
    file_rows = []
    multiple_pdf_rows = []
    publication_examples = []

    for document in documents:
        ntrs_id = document["ntrs_id"]
        title = document.get("title") or ""
        files = document.get("files") or []
        has_pdf = bool(files)
        document_type = document.get("document_type") or "UNSPECIFIED"

        types_all[document_type] += 1
        if has_pdf:
            types_local[document_type] += 1

        queries = set(document.get("search_queries") or [])
        query_sets[ntrs_id] = queries
        query_count_distribution[len(queries)] += 1

        for query in queries:
            queries_all[query] += 1
            if has_pdf:
                queries_local[query] += 1

        if len(files) > 1:
            multiple_pdf_rows.append({
                "ntrs_id": ntrs_id,
                "title": title,
                "pdf_count": len(files),
                "files": "; ".join(item["file"] for item in files),
                "total_pages": sum(item.get("pages") or 0 for item in files),
            })

        for item in files:
            file_rows.append({
                "ntrs_id": ntrs_id,
                "title": title,
                "file": item["file"],
                "relative_path": item["relative_path"],
                "size_bytes": item.get("size_bytes"),
                "pages": item.get("pages"),
                "text_chars": item.get("text_chars"),
                "pages_with_text": item.get("pages_with_text"),
                "page_text_errors": item.get("page_text_errors"),
                "status": item.get("status"),
                "error": item.get("error") or "",
            })

        record = (
            document.get("source_candidate", {}).get("record") or {}
        )
        publications = record.get("publications")

        if publications and len(publication_examples) < 10:
            publication_examples.append({
                "ntrs_id": ntrs_id,
                "title": title,
                "has_local_pdf": has_pdf,
                "publications": publications,
            })

    type_rows = [
        {
            "document_type": kind,
            "candidate_records": types_all[kind],
            "records_with_pdf": types_local[kind],
            "records_without_pdf": types_all[kind] - types_local[kind],
        }
        for kind in sorted(types_all, key=lambda key: (-types_all[key], key))
    ]
    write_csv(
        "document_types.csv",
        type_rows,
        [
            "document_type", "candidate_records",
            "records_with_pdf", "records_without_pdf",
        ],
    )

    query_rows = [
        {
            "query": query,
            "candidate_records": queries_all[query],
            "records_with_pdf": queries_local[query],
            "records_without_pdf": queries_all[query] - queries_local[query],
        }
        for query in sorted(
            queries_all, key=lambda key: (-queries_all[key], key)
        )
    ]
    write_csv(
        "search_queries.csv",
        query_rows,
        [
            "query", "candidate_records",
            "records_with_pdf", "records_without_pdf",
        ],
    )

    pair_counts = defaultdict(lambda: [0, 0])
    for document in documents:
        queries = sorted(query_sets[document["ntrs_id"]])
        for index, first in enumerate(queries):
            for second in queries[index + 1:]:
                counts = pair_counts[(first, second)]
                counts[0] += 1
                counts[1] += bool(document.get("files"))

    overlap_rows = [
        {
            "query_a": first,
            "query_b": second,
            "shared_candidate_records": counts[0],
            "shared_records_with_pdf": counts[1],
        }
        for (first, second), counts in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1][0], item[0]),
        )
    ]
    write_csv(
        "query_overlaps.csv",
        overlap_rows,
        [
            "query_a", "query_b", "shared_candidate_records",
            "shared_records_with_pdf",
        ],
    )

    bucket_order = [
        "0", "1-5", "6-20", "21-50",
        "51-100", "101-300", "301+", "unknown",
    ]
    bucket_counts = Counter(
        page_bucket(item["pages"]) for item in file_rows
    )
    write_csv(
        "page_distribution.csv",
        [
            {"page_range": bucket, "pdf_files": bucket_counts[bucket]}
            for bucket in bucket_order
        ],
        ["page_range", "pdf_files"],
    )

    file_fields = [
        "ntrs_id", "title", "file", "relative_path",
        "size_bytes", "pages", "text_chars",
        "pages_with_text", "page_text_errors", "status", "error",
    ]
    largest = sorted(
        file_rows,
        key=lambda item: (
            item["pages"] if item["pages"] is not None else -1,
            item["size_bytes"] or 0,
        ),
        reverse=True,
    )
    write_csv("largest_pdfs.csv", largest[:30], file_fields)

    problem_files = [
        item for item in file_rows
        if item["status"] != "text_extracted"
    ]
    write_csv("files_to_review.csv", problem_files, file_fields)

    write_csv(
        "records_with_multiple_pdfs.csv",
        multiple_pdf_rows,
        ["ntrs_id", "title", "pdf_count", "files", "total_pages"],
    )

    (OUT / "publication_examples.json").write_text(
        json.dumps(publication_examples, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    pages = [
        item["pages"] for item in file_rows
        if item["pages"] is not None
    ]
    records_with_pdf = sum(bool(item.get("files")) for item in documents)
    statuses = Counter(item["status"] for item in file_rows)

    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_records": len(documents),
        "records_with_local_pdf": records_with_pdf,
        "records_without_local_pdf": len(documents) - records_with_pdf,
        "matched_pdf_files": len(file_rows),
        "unmatched_pdf_files": len(corpus.get("unmatched_pdf_files", [])),
        "records_with_multiple_pdfs": len(multiple_pdf_rows),
        "total_pdf_bytes": sum(
            item["size_bytes"] or 0 for item in file_rows
        ),
        "total_pages": sum(pages),
        "pdfs_with_known_page_count": len(pages),
        "mean_pages_per_pdf_with_known_count": (
            round(sum(pages) / len(pages), 2) if pages else None
        ),
        "median_pages_per_pdf_with_known_count": (
            median(pages) if pages else None
        ),
        "min_pages": min(pages) if pages else None,
        "max_pages": max(pages) if pages else None,
        "extracted_text_chars": sum(
            item["text_chars"] or 0 for item in file_rows
        ),
        "pdf_statuses": dict(sorted(statuses.items())),
        "distinct_search_queries": len(queries_all),
        "records_found_by_multiple_queries": sum(
            count for number, count in query_count_distribution.items()
            if number > 1
        ),
        "records_by_number_of_search_queries": {
            str(number): count
            for number, count in sorted(query_count_distribution.items())
        },
        "top_document_types": type_rows[:10],
        "top_search_queries": query_rows[:10],
        "scope": "matched PDFs and all candidate metadata records",
        "relevance": "UNREVIEWED",
        "publication_year_analysis_performed": False,
        "notes": [
            "Search query counts overlap and must not be summed as unique records.",
            "PDF presence does not establish thematic relevance.",
            "Page totals count files, including multiple PDFs per record.",
            "No extracted full text is stored by this script.",
        ],
    }

    (OUT / "analytics_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("ANALYTICS COMPLETE")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nOutput folder: {OUT}")


if __name__ == "__main__":
    main()
