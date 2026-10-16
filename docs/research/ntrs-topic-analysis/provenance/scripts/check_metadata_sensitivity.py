import csv
import hashlib
import json
import re
import warnings
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.sparse import load_npz
from sklearn.decomposition import NMF
from sklearn.exceptions import ConvergenceWarning
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "data/ntrs/research"
FEATURES = BASE / "features_metadata_v1"
MODELS = BASE / "nmf_metadata_v1"
ASSESSMENT = BASE / "nmf_metadata_stability_v1"
CORPUS = BASE / "metadata_corpus_v1/documents.jsonl"
DUPLICATES = BASE / "metadata_audit_v1/exact_duplicate_groups.csv"
OUT = BASE / "metadata_sensitivity_v1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def align(A, B):
    similarity = np.clip(
        normalize(A, norm="l2") @ normalize(B, norm="l2").T,
        0.0, 1.0,
    )
    left, right = linear_sum_assignment(-similarity)
    mapping = np.empty(A.shape[0], dtype=int)
    mapping[left] = right
    return mapping, similarity[left, right]


def relative_weights(W, H):
    scaled = W * H.sum(axis=1)[None, :]
    totals = scaled.sum(axis=1)
    if np.any(totals <= 0):
        raise RuntimeError("Empty document profile.")
    return scaled / totals[:, None]


def main():
    if OUT.exists():
        raise SystemExit(f"Output already exists: {OUT}")

    experiment = json.loads(
        (MODELS / "experiment.json").read_text(encoding="utf-8")
    )
    features_manifest = json.loads(
        (FEATURES / "feature_manifest.json").read_text(encoding="utf-8")
    )

    for name, key in [
        ("tfidf.npz", "matrix_sha256"),
        ("record_order.csv", "record_order_sha256"),
        ("vocabulary.csv", "vocabulary_sha256"),
    ]:
        if sha256(FEATURES / name) != experiment[key]:
            raise SystemExit(f"Checksum mismatch: {name}")

    if sha256(CORPUS) != features_manifest["input_documents_sha256"]:
        raise SystemExit("Metadata corpus checksum mismatch.")

    records = read_csv(FEATURES / "record_order.csv")
    ids = [row["ntrs_id"] for row in records]
    if any(int(row["matrix_row"]) != i for i, row in enumerate(records)):
        raise SystemExit("Record order mismatch.")

    X = load_npz(FEATURES / "tfidf.npz").tocsr()
    if X.shape[0] != len(ids):
        raise SystemExit("Matrix row mismatch.")

    abstract_lengths = {}
    with CORPUS.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            abstract_lengths[row["ntrs_id"]] = len(
                re.findall(r"\b\w+\b", row["abstract"])
            )

    if set(ids) != set(abstract_lengths):
        raise SystemExit("Metadata record set mismatch.")

    removed_duplicates = set()
    duplicate_groups = []

    for row in read_csv(DUPLICATES):
        if row["field"] != "title_and_abstract":
            continue
        members = sorted(row["ntrs_ids"].split("|"))
        if not set(members).issubset(set(ids)):
            raise SystemExit("Duplicate group contains missing records.")
        removed_duplicates.update(members[1:])
        duplicate_groups.append({
            "kept": members[0],
            "removed": members[1:],
        })

    scenarios = {
        "collapse_identical_metadata": [
            i for i, record_id in enumerate(ids)
            if record_id not in removed_duplicates
        ],
        "abstract_at_least_20_words": [
            i for i, record_id in enumerate(ids)
            if abstract_lengths[record_id] >= 20
        ],
    }

    baseline_row = next(
        row for row in read_csv(ASSESSMENT / "stability_summary.csv")
        if int(row["k"]) == 10
    )
    ref_seed = int(baseline_row["representative_seed"])
    reference_path = (
        MODELS / f"k10_seed{ref_seed:02d}" / "factors.npz"
    )

    with np.load(reference_path) as data:
        H_ref = data["H"].copy()
        Q_ref = data["Q"].copy()

    if Q_ref.shape != (len(ids), 10):
        raise SystemExit("Reference profile shape mismatch.")

    OUT.mkdir(parents=True)
    run_rows = []
    topic_rows = []
    summaries = []

    for name, indices in scenarios.items():
        folder = OUT / name
        folder.mkdir()
        indices = np.asarray(indices, dtype=int)
        selected = set(indices.tolist())
        removed_ids = [
            record_id for i, record_id in enumerate(ids)
            if i not in selected
        ]

        (folder / "selection.json").write_text(
            json.dumps({
                "retained_ids": [ids[i] for i in indices],
                "excluded_ids": removed_ids,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        topic_vectors = []
        reference_scores = []
        weight_deltas = []
        topic_ref_scores = []

        for seed in experiment["seeds"]:
            print(f"FIT {name}, seed={seed}", flush=True)
            model = NMF(
                n_components=10,
                random_state=seed,
                **experiment["parameters"],
            )

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                W = model.fit_transform(X[indices])

            H = model.components_
            if np.any(H.sum(axis=1) <= 0):
                raise RuntimeError("Empty topic component.")

            Q = relative_weights(W, H)
            mapping, scores = align(H_ref, H)
            Q_aligned = Q[:, mapping]

            baseline_mean = Q_ref[indices].mean(axis=0)
            new_mean = Q_aligned.mean(axis=0)
            delta = new_mean - baseline_mean

            np.savez_compressed(
                folder / f"seed{seed:02d}.npz",
                H=H,
                W=W,
                Q_aligned=Q_aligned,
                reference_to_new_topic=mapping,
                retained_matrix_rows=indices,
            )

            convergence_warning = any(
                issubclass(item.category, ConvergenceWarning)
                for item in caught
            )

            run_rows.append({
                "scenario": name,
                "seed": seed,
                "records": len(indices),
                "mean_cosine_to_reference": float(scores.mean()),
                "min_cosine_to_reference": float(scores.min()),
                "mean_document_profile_l1_change": float(
                    np.abs(Q_aligned - Q_ref[indices]).sum(axis=1).mean()
                ),
                "convergence_warning": convergence_warning,
                "iterations": int(model.n_iter_),
            })

            topic_vectors.append(H)
            reference_scores.append(float(scores.mean()))
            weight_deltas.append(delta)
            topic_ref_scores.append(scores)

        pair_scores = []
        for a, b in combinations(topic_vectors, 2):
            _, scores = align(a, b)
            pair_scores.append(float(scores.mean()))

        deltas = np.asarray(weight_deltas)
        scores = np.asarray(topic_ref_scores)

        for topic in range(10):
            topic_rows.append({
                "scenario": name,
                "reference_topic": topic,
                "mean_cosine_to_reference": float(scores[:, topic].mean()),
                "min_cosine_to_reference": float(scores[:, topic].min()),
                "mean_weight_change_percentage_points": float(
                    100 * deltas[:, topic].mean()
                ),
                "min_weight_change_percentage_points": float(
                    100 * deltas[:, topic].min()
                ),
                "max_weight_change_percentage_points": float(
                    100 * deltas[:, topic].max()
                ),
            })

        summaries.append({
            "scenario": name,
            "retained_records": len(indices),
            "excluded_records": len(removed_ids),
            "mean_pairwise_cosine": float(np.mean(pair_scores)),
            "mean_cosine_to_reference": float(np.mean(reference_scores)),
            "convergence_warnings": sum(
                row["convergence_warning"] for row in run_rows
                if row["scenario"] == name
            ),
        })

    write_csv(OUT / "run_metrics.csv", run_rows)
    write_csv(OUT / "topic_changes.csv", topic_rows)

    (OUT / "manifest.json").write_text(
        json.dumps({
            "script_sha256": sha256(Path(__file__)),
            "experiment_sha256": sha256(MODELS / "experiment.json"),
            "reference_factors_sha256": sha256(reference_path),
            "duplicates_file_sha256": sha256(DUPLICATES),
            "matrix_sha256": sha256(FEATURES / "tfidf.npz"),
            "reference_seed": ref_seed,
            "duplicate_groups": duplicate_groups,
            "summary": summaries,
            "method": {
                "k": 10,
                "vocabulary_and_idf": "fixed from baseline",
                "topic_alignment": "maximum-sum cosine assignment",
                "weight_comparison": (
                    "new model versus baseline, both averaged "
                    "over the same retained records"
                ),
            },
            "limitations": [
                "Scenarios are separate, not combined.",
                "Reference comparison includes initialization variability.",
                "Forced topic alignment does not prove semantic equivalence.",
                "No full-pipeline vocabulary or IDF refitting.",
                "Short abstracts are not declared invalid.",
                "Identical metadata are not proven duplicate publications.",
                "Weight ranges are not confidence intervals.",
            ],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nMETADATA SENSITIVITY COMPLETED")
    for row in summaries:
        print(json.dumps(row, ensure_ascii=False))

    print("\nTOPIC CHANGES")
    for row in topic_rows:
        print(
            f"{row['scenario']} | topic={row['reference_topic']} | "
            f"cosine={row['mean_cosine_to_reference']:.3f} | "
            f"delta_pp={row['mean_weight_change_percentage_points']:+.2f}"
        )


if __name__ == "__main__":
    main()
