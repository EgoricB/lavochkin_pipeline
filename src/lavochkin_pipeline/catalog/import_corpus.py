"""Import the existing NTRS JSONL corpus without changing atlas files."""
import argparse
import base64
import hashlib
import json
from getpass import getpass
from pathlib import Path


def normalize_nuls(value):
    if isinstance(value, str):
        return value.replace("\x00", "�")
    if isinstance(value, list):
        return [normalize_nuls(item) for item in value]
    if isinstance(value, dict):
        if any("\x00" in key for key in value):
            raise ValueError("NUL in JSON key is not supported")
        return {key: normalize_nuls(item) for key, item in value.items()}
    return value


def load_corpus(path):
    records = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record must be an object")
                ident = row.get("ntrs_id")
                if isinstance(ident, bool) or not isinstance(ident, (str, int)):
                    raise ValueError("ntrs_id must be a string or integer")
                ident = str(ident).strip()
                if not ident or ident in seen:
                    raise ValueError("empty or duplicate ntrs_id")
                for field in ("title", "abstract", "text"):
                    if row.get(field) is not None and not isinstance(row[field], str):
                        raise ValueError(f"{field} must be a string or null")
                text = row.get("text") or ""
                actual = bool(text.strip())
                declared = row.get("has_nonempty_text")
                if declared is not None and (not isinstance(declared, bool) or declared != actual):
                    raise ValueError("has_nonempty_text disagrees with text")
                canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                normalized = normalize_nuls(row)
                if normalized != row:
                    if "_catalog_import" in row:
                        raise ValueError("Reserved key _catalog_import already exists")
                    normalized["_catalog_import"] = {
                        "normalization": "NUL_to_U+FFFD_v1",
                        "original_json_line_utf8_base64": base64.b64encode(line.encode("utf-8")).decode("ascii"),
                        "original_canonical_sha256": record_hash,
                    }
                records.append((ident, normalized, record_hash))
                seen.add(ident)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Line {number}: {exc}") from exc
    if not records:
        raise ValueError("Corpus is empty")
    manifest = path.parent / "manifest.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest.exists():
        expected = json.loads(manifest.read_text(encoding="utf-8-sig")).get("output_documents_sha256")
        if expected is not None and expected != digest:
            raise ValueError("Corpus checksum does not match manifest")
    return records, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("data/ntrs/research/corpus_v2/documents.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--dbname", default="lavochkin_catalog")
    parser.add_argument("--user", default="lavochkin_app")
    args = parser.parse_args()
    records, digest = load_corpus(args.corpus)
    summary = {"documents": len(records), "with_text": sum(bool((r.get("text") or "").strip()) for _, r, _ in records), "sha256": digest, "nul_normalized_records": sum("_catalog_import" in r for _, r, _ in records)}
    if args.dry_run:
        print(json.dumps({"mode": "validation_only", **summary}, indent=2))
        return
    import psycopg
    from psycopg.types.json import Jsonb
    password = getpass(f"Password for {args.user}: ")
    with psycopg.connect(host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=password, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(184703201)")
            cur.execute("SELECT 1 FROM catalog.schema_migrations WHERE version = '001_initial'")
            if cur.fetchone() is None:
                raise ValueError("Migration 001_initial is missing")
            cur.execute("INSERT INTO catalog.import_runs(source_path, source_sha256) VALUES (%s,%s) RETURNING id", (str(args.corpus), digest))
            run_id = cur.fetchone()[0]
            new_documents = new_versions = 0
            for ident, row, record_digest in records:
                cur.execute("SELECT id FROM catalog.documents WHERE ntrs_id=%s", (ident,))
                old = cur.fetchone()
                new_documents += old is None
                cur.execute("""INSERT INTO catalog.documents(ntrs_id,title,abstract,document_type)
                    VALUES (%s,%s,%s,%s) ON CONFLICT(ntrs_id) DO UPDATE SET
                    title=EXCLUDED.title, abstract=EXCLUDED.abstract,
                    document_type=EXCLUDED.document_type, updated_at=now() RETURNING id""",
                    (ident, row.get("title") or "", row.get("abstract") or "", row.get("document_type")))
                doc_id = cur.fetchone()[0]
                text = row.get("text") or ""
                cur.execute("""INSERT INTO catalog.document_versions
                    (document_id,import_run_id,record_sha256,has_nonempty_text,full_text,page_parts,page_sources,source_record)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(document_id,record_sha256) DO NOTHING RETURNING id""",
                    (doc_id, run_id, record_digest, bool(text.strip()), text,
                     Jsonb(row.get("page_parts")), Jsonb(row.get("page_sources")), Jsonb(row)))
                version = cur.fetchone()
                if version:
                    new_versions += 1
                    version_id = version[0]
                else:
                    cur.execute("SELECT id FROM catalog.document_versions WHERE document_id=%s AND record_sha256=%s", (doc_id, record_digest))
                    version_id = cur.fetchone()[0]
                cur.execute("""INSERT INTO catalog.document_current_versions(document_id,version_id)
                    VALUES (%s,%s) ON CONFLICT(document_id) DO UPDATE SET version_id=EXCLUDED.version_id""", (doc_id,version_id))
            result = {**summary, "new_documents": new_documents, "new_versions": new_versions, "run_id": run_id}
            cur.execute("UPDATE catalog.import_runs SET status='completed',finished_at=now(),statistics=%s WHERE id=%s", (Jsonb(result),run_id))
        conn.commit()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"Import failed (no partial import committed): {exc}") from exc
