import csv
import hashlib
import json
import platform
import re
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from scipy.sparse import save_npz
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/ntrs/research/metadata_corpus_v1"
OUT = ROOT / "data/ntrs/research/features_metadata_v1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if OUT.exists():
        raise SystemExit(
            f"Output already exists: {OUT}\n"
            "Existing results will not be overwritten."
        )

    input_path = SOURCE / "documents.jsonl"
    manifest = json.loads(
        (SOURCE / "manifest.json").read_text(encoding="utf-8")
    )

    input_hash = sha256(input_path)
    if input_hash != manifest["output_documents_sha256"]:
        raise SystemExit("Input checksum mismatch.")

    records = []
    excluded = []

    with input_path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            text = record["text"]

            if text.strip():
                records.append({
                    "ntrs_id": record["ntrs_id"],
                    "title": record["title"],
                    "text": text,
                })
            else:
                excluded.append(record["ntrs_id"])

    records.sort(key=lambda row: row["ntrs_id"])
    ids = [row["ntrs_id"] for row in records]

    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate record IDs.")

    params = {
        "lowercase": True,
        "strip_accents": None,
        "analyzer": "word",
        "token_pattern": r"(?u)\b[^\W\d_]{2,}\b",
        "ngram_range": (1, 1),
        "stop_words": sorted(ENGLISH_STOP_WORDS),
        "min_df": 3,
        "max_df": 0.90,
        "max_features": None,
        "binary": False,
        "sublinear_tf": True,
        "use_idf": True,
        "smooth_idf": True,
        "norm": "l2",
    }

    vectorizer = TfidfVectorizer(
        **params,
        dtype=np.float64,
    )

    print(f"Vectorizing {len(records)} records...", flush=True)
    X = vectorizer.fit_transform(
        row["text"] for row in records
    ).tocsr()

    terms = vectorizer.get_feature_names_out()
    document_frequency = np.asarray(
        (X > 0).sum(axis=0)
    ).ravel()
    total_weight = np.asarray(X.sum(axis=0)).ravel()
    features_per_record = np.diff(X.indptr)

    zero_rows = np.flatnonzero(features_per_record == 0)
    if len(zero_rows):
        raise SystemExit(
            "Records have no retained features: "
            + ", ".join(ids[i] for i in zero_rows)
            + "\nReview preprocessing before fitting models."
        )

    OUT.mkdir(parents=True)
    (OUT / "stopwords.json").write_text(
        json.dumps(params["stop_words"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    save_npz(OUT / "tfidf.npz", X)
    joblib.dump(vectorizer, OUT / "vectorizer.joblib")

    with (OUT / "record_order.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "matrix_row", "ntrs_id", "title",
                "word_tokens", "retained_features"
            ],
        )
        writer.writeheader()
        lengths = []

        for i, row in enumerate(records):
            length = len(re.findall(r"\b\w+\b", row["text"]))
            lengths.append(length)
            writer.writerow({
                "matrix_row": i,
                "ntrs_id": row["ntrs_id"],
                "title": row["title"],
                "word_tokens": length,
                "retained_features": int(features_per_record[i]),
            })

    with (OUT / "vocabulary.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "matrix_column", "term",
            "document_frequency", "idf", "total_tfidf"
        ])
        for j, term in enumerate(terms):
            writer.writerow([
                j, term,
                int(document_frequency[j]),
                float(vectorizer.idf_[j]),
                float(total_weight[j]),
            ])

    with (OUT / "frequent_terms.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(["term", "document_frequency"])
        order = sorted(
            range(len(terms)),
            key=lambda j: (-int(document_frequency[j]), terms[j]),
        )
        for j in order[:100]:
            writer.writerow([terms[j], int(document_frequency[j])])

    lengths = np.asarray(lengths, dtype=np.int64)
    largest_count = max(1, int(np.ceil(len(records) * 0.05)))
    largest_share = float(
        np.sort(lengths)[-largest_count:].sum() / lengths.sum()
    )

    summary = {
        "records_in_input": len(records) + len(excluded),
        "records_in_matrix": int(X.shape[0]),
        "excluded_empty_records": excluded,
        "vocabulary_size": int(X.shape[1]),
        "nonzero_cells": int(X.nnz),
        "zero_feature_records": int(len(zero_rows)),
        "word_tokens_percentiles": {
            str(p): float(np.percentile(lengths, p))
            for p in [0, 25, 50, 75, 90, 95, 99, 100]
        },
        "largest_5_percent_record_count": largest_count,
        "largest_5_percent_share_of_word_tokens": largest_share,
        "retained_features_median": float(
            np.median(features_per_record)
        ),
    }

    metadata = {
        "input_documents_sha256": input_hash,
        "matrix_sha256": sha256(OUT / "tfidf.npz"),
        "record_order_sha256": sha256(OUT / "record_order.csv"),
        "vectorizer_parameters": params,
        "dtype": "float64",
        "versions": {
            "python": platform.python_version(),
            **{
                package: version(package)
                for package in [
                    "numpy", "scipy", "scikit-learn", "joblib"
                ]
            },
        },
        "summary": summary,
        "limitations": [
            "Tokenization does not reconstruct hyphenated line breaks.",
            "No language-specific morphology is applied.",
            "No stop-word list or thematic dictionary is applied.",
            "Two-letter minimum excludes one-letter tokens.",
            "Numeric-only tokens are not retained.",
            "Bibliographies and repeated text remain in the input.",
        ],
    }

    (OUT / "feature_manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nFEATURE MATRIX PREPARED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nMost widespread retained terms:")
    for j in order[:30]:
        print(f"{terms[j]}\t{int(document_frequency[j])}")


if __name__ == "__main__":
    main()



