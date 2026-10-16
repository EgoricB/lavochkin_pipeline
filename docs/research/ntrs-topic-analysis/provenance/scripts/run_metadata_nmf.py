import csv
import hashlib
import json
import warnings
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from scipy.sparse import load_npz
from sklearn.decomposition import NMF
from sklearn.exceptions import ConvergenceWarning

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/ntrs/research/features_metadata_v1"
OUT = ROOT / "data/ntrs/research/nmf_metadata_v1"

TOPIC_COUNTS = [5, 10, 15, 20, 25, 30]
SEEDS = list(range(10))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = json.loads(
        (SOURCE / "feature_manifest.json").read_text(encoding="utf-8")
    )

    if sha256(SOURCE / "tfidf.npz") != manifest["matrix_sha256"]:
        raise SystemExit("Matrix checksum mismatch.")

    if sha256(SOURCE / "record_order.csv") != manifest["record_order_sha256"]:
        raise SystemExit("Record order checksum mismatch.")

    X = load_npz(SOURCE / "tfidf.npz").tocsr()

    with (SOURCE / "vocabulary.csv").open(
        encoding="utf-8-sig", newline=""
    ) as stream:
        vocabulary = list(csv.DictReader(stream))

    if len(vocabulary) != X.shape[1]:
        raise SystemExit("Vocabulary size mismatch.")

    for i, row in enumerate(vocabulary):
        if int(row["matrix_column"]) != i:
            raise SystemExit("Vocabulary order mismatch.")

    terms = [row["term"] for row in vocabulary]

    config = {
        "feature_manifest_sha256": sha256(
            SOURCE / "feature_manifest.json"
        ),
        "matrix_sha256": manifest["matrix_sha256"],
        "record_order_sha256": manifest["record_order_sha256"],
        "vocabulary_sha256": sha256(SOURCE / "vocabulary.csv"),
        "sklearn_version": version("scikit-learn"),
        "topic_counts": TOPIC_COUNTS,
        "seeds": SEEDS,
        "parameters": {
            "init": "random",
            "solver": "cd",
            "beta_loss": "frobenius",
            "tol": 0.0001,
            "max_iter": 1000,
            "alpha_W": 0.0,
            "alpha_H": 0.0,
            "l1_ratio": 0.0,
        },
    }

    if OUT.exists():
        saved_config = OUT / "experiment.json"
        if not saved_config.exists():
            raise SystemExit("Output exists without experiment configuration.")
        if json.loads(saved_config.read_text(encoding="utf-8")) != config:
            raise SystemExit("Experiment configuration mismatch.")
    else:
        OUT.mkdir(parents=True)
        (OUT / "experiment.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    results = []

    for k in TOPIC_COUNTS:
        for seed in SEEDS:
            run_dir = OUT / f"k{k:02d}_seed{seed:02d}"
            complete = run_dir / "metrics.json"

            if complete.exists():
                results.append(json.loads(
                    complete.read_text(encoding="utf-8")
                ))
                print(f"SKIP completed: k={k}, seed={seed}", flush=True)
                continue

            run_dir.mkdir(exist_ok=True)
            print(f"FIT k={k}, seed={seed}", flush=True)

            model = NMF(
                n_components=k,
                random_state=seed,
                **config["parameters"],
            )

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                W = model.fit_transform(X)

            H = model.components_

            scales = H.sum(axis=1)
            if np.any(scales <= 0):
                raise RuntimeError(
                    f"Empty topic component: k={k}, seed={seed}"
                )

            H_unit = H / scales[:, None]
            W_scaled = W * scales[None, :]
            row_sums = W_scaled.sum(axis=1)

            if np.any(row_sums <= 0):
                raise RuntimeError(
                    f"Empty document profile: k={k}, seed={seed}"
                )

            Q = W_scaled / row_sums[:, None]

            np.savez_compressed(
                run_dir / "factors.npz",
                W=W,
                H=H,
                Q=Q,
                H_l1=H_unit,
            )
            joblib.dump(model, run_dir / "model.joblib")

            with (run_dir / "topic_terms.csv").open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.writer(stream)
                writer.writerow(["topic", "rank", "term", "weight"])
                for topic in range(k):
                    top = np.argsort(
                        -H_unit[topic], kind="stable"
                    )[:30]
                    for rank, column in enumerate(top, 1):
                        writer.writerow([
                            topic, rank, terms[column],
                            float(H_unit[topic, column]),
                        ])

            metrics = {
                "k": k,
                "seed": seed,
                "iterations": int(model.n_iter_),
                "convergence_warning": any(
                    issubclass(item.category, ConvergenceWarning)
                    for item in caught
                ),
                "warnings": [str(item.message) for item in caught],
                "reconstruction_error": float(
                    model.reconstruction_err_
                ),
                "mean_relative_topic_weights": Q.mean(axis=0).tolist(),
            }

            complete.write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            results.append(metrics)

    summary = {
        "completed_runs": len(results),
        "runs_with_convergence_warning": sum(
            row["convergence_warning"] for row in results
        ),
        "topic_counts": TOPIC_COUNTS,
        "seeds": SEEDS,
    }

    (OUT / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\nNMF EXPERIMENT COMPLETED")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

