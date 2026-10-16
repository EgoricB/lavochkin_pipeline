import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/ntrs/research/corpus_v2"
OUT = ROOT / "data/ntrs/research/metadata_corpus_v1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists():
        raise SystemExit(f"Output already exists: {OUT}")

    source = SOURCE / "documents.jsonl"
    parent = json.loads(
        (SOURCE / "manifest.json").read_text(encoding="utf-8")
    )

    source_hash = sha256(source)
    if source_hash != parent["output_documents_sha256"]:
        raise SystemExit("Source checksum mismatch.")

    selected = []
    excluded = []
    common_ids = []
    seen = set()

    with source.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            record_id = str(row["ntrs_id"])

            if record_id in seen:
                raise SystemExit(f"Duplicate ID: {record_id}")
            seen.add(record_id)

            title = (row.get("title") or "").strip()
            abstract = (row.get("abstract") or "").strip()

            if not title or not abstract:
                excluded.append({
                    "ntrs_id": record_id,
                    "title": title,
                    "reason": "missing_title_or_abstract",
                })
                continue

            has_fulltext = bool(row["text"].strip())
            if has_fulltext:
                common_ids.append(record_id)

            selected.append({
                "ntrs_id": record_id,
                "title": title,
                "abstract": abstract,
                "text": title + "\n\n" + abstract,
                "has_fulltext": has_fulltext,
            })

    selected.sort(key=lambda row: row["ntrs_id"])
    OUT.mkdir(parents=True)

    output = OUT / "documents.jsonl"
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    (OUT / "excluded_records.json").write_text(
        json.dumps(excluded, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "common_fulltext_ids.json").write_text(
        json.dumps(sorted(common_ids), indent=2),
        encoding="utf-8",
    )

    summary = {
        "input_records": len(seen),
        "metadata_records": len(selected),
        "excluded_records": len(excluded),
        "common_with_fulltext": len(common_ids),
    }

    (OUT / "manifest.json").write_text(
        json.dumps({
            "parent_documents_sha256": source_hash,
            "output_documents_sha256": sha256(output),
            "script_sha256": sha256(Path(__file__)),
            "representation": "title once + abstract once",
            "short_abstracts_excluded": False,
            "duplicate_groups_removed": False,
            "summary": summary,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("METADATA CORPUS PREPARED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
