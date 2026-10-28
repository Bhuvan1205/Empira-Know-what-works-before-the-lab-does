"""Organism-probability features: P(organism group | information at culture order).
Out-of-fold (5 folds grouped by patient) on the training period; validation/test use a model fit on
the whole training period. Output: data/processed/organism_probs.parquet (one row per culture)."""
import sys, os
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import GroupKFold
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

N_GROUPS = 12
lab = pd.read_parquet(f"{C.P}/labels_organism.parquet", columns=["order_proc_id_coded", "organism"])
# main organism per culture = the one with most tested antibiotics
main = lab.groupby(["order_proc_id_coded", "organism"]).size().reset_index(name="k") \
          .sort_values("k", ascending=False).drop_duplicates("order_proc_id_coded")
top = main.organism.value_counts().head(N_GROUPS).index.tolist()
main["y"] = main.organism.where(main.organism.isin(top), "OTHER")
classes = top + ["OTHER"]
main["yi"] = main.y.map({c: i for i, c in enumerate(classes)})

cul = C.load_cultures(labs=False)
feats = [c for c in cul.columns if c not in C.ID_COLS and c != "order_proc_id_coded"]
d = cul.merge(main[["order_proc_id_coded", "yi"]], on="order_proc_id_coded")
tr = d[d.year <= C.TRAIN_END].reset_index(drop=True)
rest = d[d.year > C.TRAIN_END].reset_index(drop=True)
params = dict(objective="multiclass", num_class=len(classes), learning_rate=0.08, num_leaves=31,
              min_data_in_leaf=100, feature_fraction=0.7, bagging_fraction=0.8, bagging_freq=1,
              max_bin=63, seed=C.SEED, verbose=-1, num_threads=2)
ROUNDS = 180
oof = np.zeros((len(tr), len(classes)), dtype=np.float32)
for k, (i, j) in enumerate(GroupKFold(5).split(tr, groups=tr.anon_id)):
    m = lgb.train(params, lgb.Dataset(tr.loc[i, feats], tr.loc[i, "yi"]), ROUNDS)
    oof[j] = m.predict(tr.loc[j, feats]); print("fold", k, flush=True)
m = lgb.train(params, lgb.Dataset(tr[feats], tr.yi), ROUNDS)
os.makedirs(f"{C.MODELS}/experiments", exist_ok=True); m.save_model(f"{C.MODELS}/experiments/organism_probs.txt")
pr = m.predict(rest[feats]).astype(np.float32)
cols = [f"orgp_{i:02d}_" + C.clean([c.lower()])[0][:30] for i, c in enumerate(classes)]
C.save_json(dict(zip(cols, classes)), f"{C.MODELS}/experiments/organism_probs_classes.json")
out = pd.concat([pd.DataFrame(oof, columns=cols).assign(order_proc_id_coded=tr.order_proc_id_coded.values),
                 pd.DataFrame(pr, columns=cols).assign(order_proc_id_coded=rest.order_proc_id_coded.values)])
out.to_parquet(f"{C.P}/organism_probs.parquet", index=False)
from sklearn.metrics import log_loss, accuracy_score
yv = rest.yi.values
print("classes", classes)
print("val+test accuracy", round(accuracy_score(yv, pr.argmax(1)), 3), "majority", round((yv == np.bincount(tr.yi).argmax()).mean(), 3),
      "logloss", round(log_loss(yv, pr, labels=range(len(classes))), 3))
