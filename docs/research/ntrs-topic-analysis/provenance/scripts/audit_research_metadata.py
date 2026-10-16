import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/ntrs/research/corpus_v2"
OUT = ROOT / "data/ntrs/research/metadata_audit_v1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    return " ".join(
        unicodedata.normalize("NFKC", text).casefold().split()
    )


def word_count(text):
    return len(re.findall(r"\b\w+\b", text))


def describe(values):
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(values),
        "min": ordered[0],
        "median": median(ordered),
        "max": ordered[-1],
    }


def main():
    if OUT.exists():
        raise SystemExit(f"Output already exists: {OUT}")

    input_path = SOURCE / "documents.jsonl"
    manifest = json.loads(
        (SOURCE / "manifest.json").read_text(encoding="utf-8")
    )
    input_hash = sha256(input_path)

    if input_hash != manifest["output_documents_sha256"]:
        raise SystemExit("Source checksum mismatch.")

    rows = []
    groups = {
        "title": defaultdict(list),
        "abstract": defaultdict(list),
        "title_and_abstract": defaultdict(list),
    }
    seen = set()

    with input_path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            record_id = str(record["ntrs_id"])

            if record_id in seen:
                raise SystemExit(f"Duplicate record ID: {record_id}")
            seen.add(record_id)

            title = record.get("title") or ""
            abstract = record.get("abstract") or ""

            if not isinstance(title, str) or not isinstance(abstract, str):
                raise SystemExit(
                    f"Non-string metadata field: {record_id}"
                )

            title_key = normalize(title)
            abstract_key = normalize(abstract)

            rows.append({
                "ntrs_id": record_id,
                "title": title,
                "has_title": bool(title_key),
                "has_abstract": bool(abstract_key),
                "title_words": word_count(title),
                "abstract_words": word_count(abstract),
                "abstract_characters": len(abstract),
                "has_fulltext": bool(record["text"].strip()),
            })

            if title_key:
                groups["title"][title_key].append(record_id)
            if abstract_key:
                groups["abstract"][abstract_key].append(record_id)
            if title_key and abstract_key:
                groups["title_and_abstract"][
                    (title_key, abstract_key)
                ].append(record_id)

    if not rows:
        raise SystemExit("No records found.")

    rows.sort(key=lambda row: row["ntrs_id"])
    duplicates = []

    for field, mapping in groups.items():
        repeated = [
            ids for ids in mapping.values() if len(ids) > 1
        ]
        repeated.sort(key=lambda ids: tuple(sorted(ids)))

        for index, ids in enumerate(repeated, 1):
            duplicates.append({
                "field": field,
                "group": index,
                "record_count": len(ids),
                "ntrs_ids": "|".join(sorted(ids)),
            })

    summary = {
        "records": len(rows),
        "with_title": sum(row["has_title"] for row in rows),
        "with_abstract": sum(row["has_abstract"] for row in rows),
        "with_title_and_abstract": sum(
            row["has_title"] and row["has_abstract"] for row in rows
        ),
        "with_title_abstract_and_fulltext": sum(
            row["has_title"]
            and row["has_abstract"]
            and row["has_fulltext"]
            for row in rows
        ),
        "without_abstract": [
            row["ntrs_id"] for row in rows
            if not row["has_abstract"]
        ],
        "nonempty_abstract_word_counts": describe([
            row["abstract_words"] for row in rows
            if row["has_abstract"]
        ]),
        "abstracts_with_1_to_19_words": sum(
            row["has_abstract"] and 1 <= row["abstract_words"] < 20
            for row in rows
        ),
        "duplicate_groups": {
            field: sum(
                group["field"] == field for group in duplicates
            )
            for field in groups
        },
    }

    OUT.mkdir(parents=True)

    with (OUT / "metadata_inventory.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    with (OUT / "exact_duplicate_groups.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["field", "group", "record_count", "ntrs_ids"],
        )
        writer.writeheader()
        writer.writerows(duplicates)

    (OUT / "audit_manifest.json").write_text(
        json.dumps({
            "input_sha256": input_hash,
            "script_sha256": sha256(Path(__file__)),
            "duplicate_normalization": (
                "Unicode NFKC, casefold, collapse whitespace"
            ),
            "summary": summary,
            "limitations": [
                "Nonempty abstracts are not validated for content quality.",
                "Normalized exact matches are not proven duplicate publications.",
                "Short abstracts are counted, not excluded.",
                "No language identification is performed.",
                "Audit covers the existing 604-record research corpus.",
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("METADATA AUDIT COMPLETED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
