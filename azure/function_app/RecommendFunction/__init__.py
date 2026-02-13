# Code à mettre dans: azure/function_app/RecommendFunction/__init__.py
# (À copier-coller dans ton repo, ce n'est pas à exécuter dans le notebook)

AZURE_FUNCTION_INIT_PY = r'''
import json
import os
import pickle
import numpy as np
import pandas as pd

import azure.functions as func
from scipy.sparse import load_npz

# Cache global (évite de recharger à chaque requête)
_ENGINE = None

def _load_engine():
    """
    Charge les artefacts depuis le dossier ARTIFACTS_DIR et prépare l'objet de serving.
    Appelé une fois au cold start, puis mis en cache.
    """
    artifacts_dir = os.environ.get("ARTIFACTS_DIR", "./artifacts_lightfm_online")

    model_path = os.path.join(artifacts_dir, "lightfm_model.pkl")
    item_features_path = os.path.join(artifacts_dir, "item_features.npz")
    mappings_path = os.path.join(artifacts_dir, "mappings.pkl")
    trending_path = os.path.join(artifacts_dir, "trending.parquet")

    # Modèle
    with open(model_path, "rb") as f:
        model = pickle.load(f)

    # Features items (embeddings)
    item_features = load_npz(item_features_path)

    # Mappings
    with open(mappings_path, "rb") as f:
        m = pickle.load(f)

    user_to_idx = m["user_to_idx"]
    idx_to_item = m["idx_to_item"]
    user_seen = m["user_seen"]
    top_k = int(m.get("top_k", 5))

    # Trending fallback
    trending_df = pd.read_parquet(trending_path)
    trending_list = trending_df["article_id"].astype(int).tolist()

    # Pré-calculs
    n_items = item_features.shape[0]
    all_item_idx = np.arange(n_items, dtype=np.int32)

    return {
        "model": model,
        "item_features": item_features,
        "user_to_idx": user_to_idx,
        "idx_to_item": idx_to_item,
        "user_seen": user_seen,
        "top_k": top_k,
        "trending": trending_list,
        "all_item_idx": all_item_idx,
    }

def _recommend(engine, user_id: int, k: int):
    """
    Recommande top-k:
    - user inconnu -> trending
    - user connu -> predict + filtrage + fallback trending
    """
    if user_id not in engine["user_to_idx"]:
        return engine["trending"][:k], "trending"

    uidx = engine["user_to_idx"][user_id]
    scores = engine["model"].predict(uidx, engine["all_item_idx"], item_features=engine["item_features"])

    # On prend plus de candidats que k pour filtrer les items déjà vus
    candidate_n = min(len(scores), k * 50)
    top_idx = np.argpartition(-scores, candidate_n)[:candidate_n]
    top_idx = top_idx[np.argsort(-scores[top_idx])]

    seen = set(engine["user_seen"].get(user_id, []))
    recs = []

    for ii in top_idx:
        aid = engine["idx_to_item"][int(ii)]
        if aid in seen:
            continue
        recs.append(int(aid))
        if len(recs) >= k:
            break

    # Complète avec trending si besoin
    if len(recs) < k:
        for aid in engine["trending"]:
            if aid not in seen and aid not in recs:
                recs.append(int(aid))
            if len(recs) >= k:
                break

    return recs, "lightfm_online"

def main(req: func.HttpRequest) -> func.HttpResponse:
    global _ENGINE

    # Parse user_id
    user_id_str = req.params.get("user_id")
    if not user_id_str:
        return func.HttpResponse("Missing query parameter 'user_id'", status_code=400)

    try:
        user_id = int(user_id_str)
    except ValueError:
        return func.HttpResponse("'user_id' must be an integer", status_code=400)

    # Lazy-load engine au cold start
    if _ENGINE is None:
        _ENGINE = _load_engine()

    k = int(req.params.get("k", _ENGINE["top_k"]))

    recos, strategy = _recommend(_ENGINE, user_id=user_id, k=k)

    payload = {
        "user_id": user_id,
        "recommended_articles": recos,
        "strategy": strategy,
    }

    return func.HttpResponse(
        body=json.dumps(payload),
        status_code=200,
        mimetype="application/json",
    )
'''
print(AZURE_FUNCTION_INIT_PY[:800] + "\n...\n")

