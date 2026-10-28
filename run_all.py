"""One entry point for the whole ARMD antibiotic-resistance pipeline.

    python run_all.py                    # everything, in order (about 10 min on a 4 GB / 2-core laptop)
    python run_all.py --list             # show stages
    python run_all.py --only evaluate    # one stage
    python run_all.py --from decision    # a stage and everything after it
    python run_all.py --only test        # release checks only

Needs data/armd_stanford/ (ARMD-Stanford CSVs from Dryad). Python 3.10+, see requirements.txt.
"""
import argparse, subprocess, sys, time, os

PY = sys.executable
STAGES = [
    ("eda",         "Exploration + leakage audit",                [["src/01_eda_leakage_audit.py", "labels"], ["src/01_eda_leakage_audit.py", "audit"],
                                                                    ["src/01_eda_leakage_audit.py", "wide"], ["src/01_eda_leakage_audit.py", "merge"]]),
    ("features",    "Leakage-safe features",                      [["src/02_build_features.py", "base"], ["src/02_build_features.py", "history"],
                                                                    ["src/02_build_features.py", "own_history"], ["src/02_build_features.py", "labs_vitals"]]),
    ("baseline",    "Phase 0 baselines (report 02)",              [["src/03_train_baseline.py", "agnostic"], ["src/03_train_baseline.py", "organism"]]),
    ("experiments", "Phase A experiments (report 03)",            [["src/04_experiments.py", "per_ab", "nolabs"], ["src/04_experiments.py", "per_ab", "labs"],
                                                                    ["src/04b_organism_probs.py"], ["src/04_experiments.py", "per_ab", "orgprob", "all"],
                                                                    ["src/04_experiments.py", "shared", "shared_nolabs", "nolabs"]]),
    ("final",       "Phase A final model components + freeze",    [["src/04_experiments.py", "per_ab", "nolabs", "all"],
                                                                    ["src/04_experiments.py", "shared", "shared_t1", "nolabs", "num_leaves=127", "min_data_in_leaf=200"],
                                                                    ["src/04_experiments.py", "finalize"]]),
    ("evaluate",    "Phase B evaluation (report 04)",             [["src/05_evaluate.py", "all"]]),
    ("decision",    "Phase C decision analysis (report 05)",      [["src/06_decision_analysis.py"]]),
    ("explain",     "Phase D explainability (report 06)",         [["src/07_explain.py"]]),
    ("external",    "Phase E external validation (needs data/armd_mgb)", [["src/08_external_validate.py", "--raw", "data/armd_mgb", "--site", "mgb"]]),
    ("test",        "Release checks",                             [["tests/run_tests.py"]]),
]
DEFAULT_SKIP = {"baseline", "experiments", "external"}   # reproduce the record / need extra data; run explicitly


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--only"); ap.add_argument("--from", dest="start"); ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true", help="include baseline/experiments/external stages")
    a = ap.parse_args()
    names = [s[0] for s in STAGES]
    if a.list:
        for n, desc, _ in STAGES: print(f"{n:12s} {desc}{'  (skipped by default)' if n in DEFAULT_SKIP else ''}")
        return
    if a.only: run = [a.only]
    elif a.start: run = names[names.index(a.start):]
    else: run = [n for n in names if a.all or n not in DEFAULT_SKIP]
    if "external" in run and not (a.only == "external" or a.all) : run.remove("external")
    if "external" in run and not os.listdir("data/armd_mgb"):
        print("skip external: data/armd_mgb is empty"); run.remove("external")
    t0 = time.time()
    for n, desc, cmds in STAGES:
        if n not in run: continue
        print(f"\n=== {n}: {desc} ===", flush=True)
        for c in cmds:
            t = time.time(); r = subprocess.run([PY, "-u"] + c)
            if r.returncode: sys.exit(f"FAILED: {' '.join(c)}")
            print(f"--- {' '.join(c)}  ({time.time() - t:.0f}s)", flush=True)
    print(f"\nDone in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
