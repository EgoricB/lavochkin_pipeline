"""Validate and import representative NMF topics and document weights."""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from getpass import getpass
from pathlib import Path


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def load_inputs(directory, k):
    tp = directory / "representative_topics.csv"
    pp = directory / "representative_record_profiles.csv"
    topics = [r for r in read_rows(tp) if int(r["k"]) == k]
    rows = [r for r in read_rows(pp) if int(r["k"]) == k]
    if k < 1 or not topics or not rows:
        raise ValueError("No data for requested k")
    seeds = {int(r["representative_seed"]) for r in topics + rows}
    if len(seeds) != 1:
        raise ValueError("Expected exactly one representative seed")
    seed = next(iter(seeds))
    topic_map = {}
    for r in topics:
        t = int(r["topic"])
        if not 0 <= t < k or t in topic_map:
            raise ValueError("Duplicate or invalid topic number")
        stability = float(r["mean_matched_cosine"])
        mean = float(r["mean_relative_weight"])
        count = int(r["leading_record_count"])
        if not (math.isfinite(stability) and 0 <= stability <= 1 and math.isfinite(mean) and 0 <= mean <= 1 and count >= 0):
            raise ValueError("Invalid topic statistics")
        topic_map[t] = (r, stability, mean, count)
    if set(topic_map) != set(range(k)):
        raise ValueError("Incomplete topic list")
    profiles = {}
    for r in rows:
        ident = r["ntrs_id"].strip()
        t = int(r["topic"])
        w = float(r["relative_weight"])
        if not ident or not 0 <= t < k or not math.isfinite(w) or not 0 <= w <= 1:
            raise ValueError("Invalid profile cell")
        profile = profiles.setdefault(ident, {})
        if t in profile:
            raise ValueError(f"Duplicate profile cell: {ident}/{t}")
        profile[t] = w
    for ident, profile in profiles.items():
        if set(profile) != set(range(k)) or abs(sum(profile.values()) - 1) > 1e-8:
            raise ValueError(f"Incomplete or non-normalized profile: {ident}")
    leading = Counter(max(range(k), key=lambda t: p[t]) for p in profiles.values())
    for t, (_, _, mean, count) in topic_map.items():
        actual_mean = sum(p[t] for p in profiles.values()) / len(profiles)
        if leading[t] != count or abs(actual_mean - mean) > 1e-8:
            raise ValueError(f"Topic statistics disagree with profiles: {t}")
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tp, pp)}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    key = f"nmf-k{k}-seed{seed}-{fingerprint}"
    return topic_map, profiles, seed, hashes, fingerprint, key


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifacts", type=Path, default=Path("docs/research/ntrs-topic-analysis/artifacts"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5432)
    ap.add_argument("--dbname", default="lavochkin_catalog")
    ap.add_argument("--user", default="lavochkin_app")
    args = ap.parse_args()
    topics, profiles, seed, hashes, fingerprint, key = load_inputs(args.artifacts, args.k)
    report = {"k": args.k, "representative_seed": seed, "topics": len(topics), "profile_documents": len(profiles), "profile_cells": len(profiles) * args.k, "model_key": key}
    if args.dry_run:
        print(json.dumps({"mode": "validation_only", **report}, indent=2))
        return
    import psycopg
    from psycopg.types.json import Jsonb
    with psycopg.connect(host=args.host, port=args.port, dbname=args.dbname, user=args.user, password=getpass(f"Password for {args.user}: "), connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(184703201)")
            cur.execute("SELECT ntrs_id,id FROM catalog.documents")
            documents = dict(cur.fetchall())
            missing = set(profiles) - set(documents)
            if missing:
                raise ValueError(f"Profiles refer to missing documents: {sorted(missing)[:10]}")
            cur.execute("SELECT id FROM catalog.topic_models WHERE model_key=%s", (key,))
            existing = cur.fetchone()
            if existing:
                model_id = existing[0]
                cur.execute("SELECT count(*) FROM catalog.topics WHERE model_id=%s", (model_id,))
                nt = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM catalog.document_topics dt JOIN catalog.topics t ON t.id=dt.topic_id WHERE t.model_id=%s", (model_id,))
                nc = cur.fetchone()[0]
                if nt != args.k or nc != len(profiles)*args.k:
                    raise ValueError("Existing model has unexpected row counts; no changes made")
                result = {**report, "status": "already_imported", "new_topics": 0, "new_profile_cells": 0}
            else:
                cur.execute("INSERT INTO catalog.import_runs(source_path,source_sha256) VALUES (%s,%s) RETURNING id", (str(args.artifacts),fingerprint))
                run_id = cur.fetchone()[0]
                cur.execute("""INSERT INTO catalog.topic_models(model_key,method,topic_count,representative_seed,parameters,provenance)
                    VALUES (%s,'NMF',%s,%s,%s,%s) RETURNING id""", (key,args.k,seed,Jsonb({"weights":"relative; sum per document equals 1", "training_parameters":"not supplied by these CSV files"}),Jsonb({"files_sha256":hashes,"artifacts_path":str(args.artifacts)})))
                model_id = cur.fetchone()[0]
                topic_ids = {}
                for t in sorted(topics):
                    row, stability, _, _ = topics[t]
                    cur.execute("INSERT INTO catalog.topics(model_id,topic_number,top_terms,mean_matched_cosine) VALUES (%s,%s,%s,%s) RETURNING id", (model_id,t,Jsonb(row["top_terms"].split(" | ")),stability))
                    topic_ids[t] = cur.fetchone()[0]
                cur.executemany("INSERT INTO catalog.document_topics(document_id,topic_id,relative_weight,import_run_id) VALUES (%s,%s,%s,%s)", ((documents[ident],topic_ids[t],p[t],run_id) for ident,p in profiles.items() for t in range(args.k)))
                result = {**report,"status":"imported","new_topics":args.k,"new_profile_cells":len(profiles)*args.k,"documents_without_profile":len(documents)-len(profiles),"run_id":run_id}
                cur.execute("UPDATE catalog.import_runs SET status='completed',finished_at=now(),statistics=%s WHERE id=%s", (Jsonb(result),run_id))
        conn.commit()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"Topic import failed (no partial import committed): {exc}") from exc
