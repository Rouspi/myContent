import json
import os
import pickle
import tempfile
import numpy as np
import pandas as pd
import azure.functions as func

from scipy.sparse import load_npz
from azure.storage.blob import BlobServiceClient

_ENGINE = None  # cache global

def _download_blob_to(path: str, container: str, blob_name: str, conn_str: str) -> None:
    """Télécharge un blob vers un fichier local."""
    bsc = BlobServiceClient.from_connection_string(conn_str)
    blob_client = bsc.get_blob_client(container=container, blob=blob_name)
    with open(path, "wb") as f:
        f.write(blob_client.download_blob().readall())

def _load_engine():
    """Charge les artefacts depuis Blob vers /tmp, puis construit l'objet de serving."""
    conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.environ.get("ARTIFACTS_CONTAINER", "artifacts")
    prefix = os.environ.get("ARTIFACTS_PREFIX", "artifacts_lightfm_online").rstrip("/")

    # Dossier temporaire (Linux Functions: /tmp)
    tmpdir = tempfile.mkdtemp(prefix="mycontent_artifacts_")

    model_path = os.path.join(tmpdir, "lightfm_model.pkl")
    item_features_path = os.path.join(tmpdir, "item_features.npz")
    mappings_path = os.path.join(tmpdir, "mappings.pkl")
    trending_path = os.path.join(tmpdir, "trending.parquet")

    # Téléchargements
    _download_blob_to(model_path, container, f"{prefix}/lightfm_model.pkl", conn_str)
    _download_blob_to(item_features_path, container, f"{prefix}/item_features.npz", conn_str)
    _download_blob_to(mappings_path, container, f"{prefix}/mappings.pkl", conn_str)
    _download_blob_to(trending_path, container, f"{prefix}/trending.parquet", conn_str)

    # Chargements
    with open(model_path, "rb") as f:
        model = pickle.load(f)

    item_features = load_npz(item_features_path)

    with open(mappings_path, "rb") as f:
        m = pickle.load(f)

    user_to_idx = m["user_to_idx"]
    idx_to_item = m["idx_to_item"]
    user_seen = m["user_seen"]
    top_k = int(m.get("top_k", 5))

    trending_df = pd.read_parquet(trending_path)
    trending_list = trending_df["article_id"].astype(int).tolist()

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
    """Reco online: predict + filtrage seen + fallback trending."""
    if user_id not in engine["user_to_idx"]:
        return engine["trending"][:k], "trending"

    uidx = engine["user_to_idx"][user_id]
    scores = engine["model"].predict(uidx, engine["all_item_idx"], item_features=engine["item_features"])

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

    if len(recs) < k:
        for aid in engine["trending"]:
            if aid not in seen and aid not in recs:
                recs.append(int(aid))
            if len(recs) >= k:
                break

    return recs, "lightfm_online"

def main(req: func.HttpRequest) -> func.HttpResponse:
    global _ENGINE

    user_id_str = req.params.get("user_id")
    if not user_id_str:
        return func.HttpResponse("Missing query parameter 'user_id'", status_code=400)

    try:
        user_id = int(user_id_str)
    except ValueError:
        return func.HttpResponse("'user_id' must be an integer", status_code=400)

    # Lazy load au cold start
    if _ENGINE is None:
        _ENGINE = _load_engine()

    k = int(req.params.get("k", _ENGINE["top_k"]))
    recos, strategy = _recommend(_ENGINE, user_id=user_id, k=k)

    return func.HttpResponse(
        body=json.dumps({"user_id": user_id, "recommended_articles": recos, "strategy": strategy}),
        mimetype="application/json",
        status_code=200,
    )

