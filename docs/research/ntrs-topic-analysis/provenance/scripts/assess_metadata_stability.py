import csv
import hashlib
import json
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parent
FEATURES = ROOT / "data/ntrs/research/features_metadata_v1"
MODELS = ROOT / "data/ntrs/research/nmf_metadata_v1"
OUT = ROOT / "data/ntrs/research/nmf_metadata_stability_v1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def match_topics(A, B):
    similarity = np.clip(A @ B.T, 0.0, 1.0)
    left, right = linear_sum_assignment(-similarity)
    return left, right, similarity[left, right]


def main():
    if OUT.exists():
        raise SystemExit(
            f"Output already exists: {OUT}\n"
            "Existing results will not be overwritten."
        )

    experiment = json.loads(
        (MODELS / "experiment.json").read_text(encoding="utf-8")
    )

    checks = [
        ("tfidf.npz", "matrix_sha256"),
        ("record_order.csv", "record_order_sha256"),
        ("vocabulary.csv", "vocabulary_sha256"),
    ]
    for name, key in checks:
        if sha256(FEATURES / name) != experiment[key]:
            raise SystemExit(f"Input checksum mismatch: {name}")

    with (FEATURES / "vocabulary.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        vocab_rows = list(csv.DictReader(stream))

    for i, row in enumerate(vocab_rows):
        if int(row["matrix_column"]) != i:
            raise SystemExit("Vocabulary order mismatch.")
    terms = [row["term"] for row in vocab_rows]

    with (FEATURES / "record_order.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        records = list(csv.DictReader(stream))

    for i, row in enumerate(records):
        if int(row["matrix_row"]) != i:
            raise SystemExit("Record order mismatch.")

    seeds = experiment["seeds"]
    topic_counts = experiment["topic_counts"]

    OUT.mkdir(parents=True)

    summaries = []
    pair_rows = []
    topic_rows = []
    example_rows = []
    profiles = []
    input_hashes = []

    for k in topic_counts:
        print(f"Assessing k={k}...", flush=True)
        runs = {}

        for seed in seeds:
            folder = MODELS / f"k{k:02d}_seed{seed:02d}"
            factor_path = folder / "factors.npz"
            metrics_path = folder / "metrics.json"

            metrics = json.loads(
                metrics_path.read_text(encoding="utf-8")
            )

            with np.load(factor_path) as data:
                H = data["H_l1"].copy()
                Q = data["Q"].copy()

            if H.shape != (k, len(terms)):
                raise SystemExit("Unexpected topic matrix shape.")
            if Q.shape != (len(records), k):
                raise SystemExit("Unexpected document matrix shape.")
            if not np.isfinite(H).all() or not np.isfinite(Q).all():
                raise SystemExit("Non-finite factor values.")
            if not np.allclose(Q.sum(axis=1), 1.0):
                raise SystemExit("Document profiles are not normalized.")

            runs[seed] = {
                "H": H,
                "H_cos": normalize(H, norm="l2", axis=1),
                "Q": Q,
                "metrics": metrics,
            }

            input_hashes.append({
                "path": str(factor_path.relative_to(ROOT)),
                "sha256": sha256(factor_path),
                "metrics_sha256": sha256(metrics_path),
            })

        scores_by_seed = {seed: [] for seed in seeds}
        all_scores = []
        pair_means = []

        for seed_a, seed_b in combinations(seeds, 2):
            _, _, values = match_topics(
                runs[seed_a]["H_cos"],
                runs[seed_b]["H_cos"],
            )
            mean_score = float(values.mean())
            pair_means.append(mean_score)
            all_scores.extend(values.tolist())
            scores_by_seed[seed_a].append(mean_score)
            scores_by_seed[seed_b].append(mean_score)

            pair_rows.append({
                "k": k,
                "seed_a": seed_a,
                "seed_b": seed_b,
                "mean_matched_cosine": mean_score,
                "min_matched_cosine": float(values.min()),
                "median_matched_cosine": float(np.median(values)),
            })

        representative = max(
            seeds,
            key=lambda seed: (
                float(np.mean(scores_by_seed[seed])),
                -seed,
            ),
        )

        ref = runs[representative]
        per_topic = [[] for _ in range(k)]
        per_topic_overlap = [[] for _ in range(k)]
        top_n = min(20, len(terms))
        ref_top = [
            set(np.argsort(-row, kind="stable")[:top_n])
            for row in ref["H"]
        ]

        for seed in seeds:
            if seed == representative:
                continue

            left, right, values = match_topics(
                ref["H_cos"], runs[seed]["H_cos"]
            )

            for i, j, value in zip(left, right, values):
                other_top = set(np.argsort(
                    -runs[seed]["H"][j], kind="stable"
                )[:top_n])
                per_topic[i].append(float(value))
                per_topic_overlap[i].append(
                    len(ref_top[i] & other_top) / top_n
                )

        within = np.clip(
            ref["H_cos"] @ ref["H_cos"].T, 0.0, 1.0
        )
        within_pairs = within[np.triu_indices(k, 1)]

        mean_weights = ref["Q"].mean(axis=0)
        leading = np.argmax(ref["Q"], axis=1)
        topic_stabilities = [
            float(np.mean(values)) for values in per_topic
        ]

        for topic in range(k):
            top_columns = np.argsort(
                -ref["H"][topic], kind="stable"
            )[:20]
            row = {
                "k": k,
                "representative_seed": representative,
                "topic": topic,
                "mean_matched_cosine": topic_stabilities[topic],
                "min_matched_cosine": min(per_topic[topic]),
                "mean_top20_overlap_fraction": float(
                    np.mean(per_topic_overlap[topic])
                ),
                "mean_relative_weight": float(mean_weights[topic]),
                "leading_record_count": int(
                    np.sum(leading == topic)
                ),
                "top_terms": " | ".join(
                    terms[column] for column in top_columns
                ),
            }
            topic_rows.append(row)

            example_order = np.argsort(
                -ref["Q"][:, topic], kind="stable"
            )[:5]
            for rank, document_index in enumerate(example_order, 1):
                record = records[document_index]
                example_rows.append({
                    "k": k,
                    "representative_seed": representative,
                    "topic": topic,
                    "rank": rank,
                    "ntrs_id": record["ntrs_id"],
                    "title": record["title"],
                    "relative_topic_weight": float(
                        ref["Q"][document_index, topic]
                    ),
                    "word_tokens": record["word_tokens"],
                })

        for index, record in enumerate(records):
            for topic in range(k):
                profiles.append({
                    "k": k,
                    "representative_seed": representative,
                    "ntrs_id": record["ntrs_id"],
                    "topic": topic,
                    "relative_weight": float(ref["Q"][index, topic]),
                })

        summaries.append({
            "k": k,
            "representative_seed": representative,
            "pairwise_mean_cosine": float(np.mean(pair_means)),
            "pairwise_min_mean_cosine": float(np.min(pair_means)),
            "matched_cosine_p10": float(
                np.percentile(all_scores, 10)
            ),
            "weakest_representative_topic_mean_cosine": min(
                topic_stabilities
            ),
            "max_within_model_topic_cosine": float(
                within_pairs.max()
            ),
            "median_reconstruction_error": float(np.median([
                runs[seed]["metrics"]["reconstruction_error"]
                for seed in seeds
            ])),
        })

    write_csv(
        OUT / "stability_summary.csv",
        summaries, list(summaries[0]),
    )
    write_csv(
        OUT / "pairwise_stability.csv",
        pair_rows, list(pair_rows[0]),
    )
    write_csv(
        OUT / "representative_topics.csv",
        topic_rows, list(topic_rows[0]),
    )
    write_csv(
        OUT / "representative_examples.csv",
        example_rows, list(example_rows[0]),
    )
    write_csv(
        OUT / "representative_record_profiles.csv",
        profiles, list(profiles[0]),
    )

    (OUT / "assessment_manifest.json").write_text(
        json.dumps({
            "experiment_sha256": sha256(
                MODELS / "experiment.json"
            ),
            "input_factor_files": input_hashes,
            "method": {
                "topic_similarity": "cosine over full term vectors",
                "matching": "maximum-sum one-to-one assignment",
                "representative": (
                    "seed with highest mean pairwise matched cosine; "
                    "ties resolved by lowest seed"
                ),
                "top_term_overlap": "intersection size divided by 20",
                "examples": "highest relative document topic weight",
            },
            "limitations": [
                "Only initialization stability is measured.",
                "No resampling or preprocessing sensitivity is measured.",
                "Representative selection can favor a dominant solution family.",
                "Stability is not semantic correctness.",
                "Example ranks are not validated relevance scores.",
                "No topic count is automatically selected.",
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nSTABILITY ASSESSMENT COMPLETED")
    for row in summaries:
        print(json.dumps(row, ensure_ascii=False))

    print("\nTOPICS AT K=10 (diagnostic view, not selected model)")
    for row in topic_rows:
        if row["k"] == 10:
            print(
                f"topic={row['topic']} "
                f"stability={row['mean_matched_cosine']:.3f} "
                f"weight={row['mean_relative_weight']:.3f}\n"
                f"  {row['top_terms']}"
            )


if __name__ == "__main__":
    main()

