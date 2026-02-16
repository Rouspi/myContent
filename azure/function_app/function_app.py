# azure/function_app/function_app.py
# Azure Functions (Python v2) — Endpoint:
#   GET /api/recommend?user_id=...&k=5
#
# Principe:
# - Cold start: téléchargement + chargement des artefacts depuis Azure Blob (modèle, matrices, mappings, trending).
# - Warm calls: inférence LightFM (ou fallback trending si user inconnu), renvoi JSON.

import json
import logging
import os
import pickle
import tempfile

import azure.functions as func
import numpy as np
import pandas as pd
from azure.storage.blob import BlobServiceClient
from scipy.sparse import load_npz

# --- Déclaration de l'app Functions (Python v2)
app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# --- Cache global du moteur (pour éviter de recharger à chaque requête)
_ENGINE = None


# _download_blob_to: télécharge un blob dans un fichier local.
def _download_blob_to(path: str, container: str, blob_name: str, conn_str: str) -> None:
    """Télécharge un blob Azure Storage vers un fichier local (binaire)."""
    # Client Blob (à partir du connection string)
    bsc = BlobServiceClient.from_connection_string(conn_str)
    blob_client = bsc.get_blob_client(container=container, blob=blob_name)

    # Téléchargement complet dans un fichier local
    with open(path, "wb") as f:
        f.write(blob_client.download_blob().readall())


# _load_engine_from_blob: charge tous les artefacts nécessaires à l'inférence.
def _load_engine_from_blob() -> dict:
    """
    Télécharge et charge les artefacts depuis Blob vers un dossier temporaire,
    puis prépare les structures pour l'inférence (predict).
    """
    # --- Lecture des paramètres d'environnement (config Azure)
    conn_str = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.environ.get("ARTIFACTS_CONTAINER", "artifacts")
    prefix = os.environ.get("ARTIFACTS_PREFIX", "").strip("/")

    # --- Utilitaire: construit le chemin du blob (prefix vide -> fichier à la racine)
    def bn(filename: str) -> str:
        return f"{prefix}/{filename}" if prefix else filename

    # --- Dossier temporaire local (sur Azure Linux: /tmp)
    tmpdir = tempfile.mkdtemp(prefix="mycontent_artifacts_")

    # --- Chemins locaux des fichiers téléchargés
    model_path = os.path.join(tmpdir, "lightfm_model.pkl")
    item_features_path = os.path.join(tmpdir, "item_features.npz")
    mappings_path = os.path.join(tmpdir, "mappings.pkl")
    trending_path = os.path.join(tmpdir, "trending.parquet")

    # --- Téléchargement des artefacts depuis Blob
    logging.info("Downloading artifacts from Blob container=%s prefix=%s ...", container, prefix or "<root>")
    _download_blob_to(model_path, container, bn("lightfm_model.pkl"), conn_str)
    _download_blob_to(item_features_path, container, bn("item_features.npz"), conn_str)
    _download_blob_to(mappings_path, container, bn("mappings.pkl"), conn_str)
    _download_blob_to(trending_path, container, bn("trending.parquet"), conn_str)

    # --- Chargement en mémoire (modèle + matrices + mappings)
    logging.info("Artifacts downloaded. Loading into memory...")

    # Modèle LightFM
    with open(model_path, "rb") as f:
        model = pickle.load(f)

    # Features items (sparse)
    item_features = load_npz(item_features_path)

    # Mappings (user_to_idx, idx_to_item, user_seen, top_k)
    with open(mappings_path, "rb") as f:
        m = pickle.load(f)

    user_to_idx = m["user_to_idx"]
    idx_to_item = m["idx_to_item"]
    user_seen = m["user_seen"]
    top_k = int(m.get("top_k", 5))

    # Trending fallback (liste d'articles les plus populaires)
    trending_df = pd.read_parquet(trending_path)
    trending_list = trending_df["article_id"].astype(int).tolist()

    # --- Pré-calcul: indices de tous les items (utilisé par model.predict)
    n_items = item_features.shape[0]
    all_item_idx = np.arange(n_items, dtype=np.int32)

    logging.info("Engine loaded: users=%d items=%d top_k=%d", len(user_to_idx), n_items, top_k)

    # --- Retourne un dict "engine" unique pour servir les requêtes
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


# _recommend: produit une reco top-k (LightFM ou trending).
def _recommend(engine: dict, user_id: int, k: int) -> tuple[list[int], str]:
    """
    Recommande top-k articles :
    - user inconnu => trending
    - user connu  => LightFM predict + filtrage des articles déjà vus + fallback trending
    """
    # --- Cas cold start user: aucun historique, on renvoie le trending
    if user_id not in engine["user_to_idx"]:
        return engine["trending"][:k], "trending"

    # --- Scoring LightFM pour tous les items
    uidx = engine["user_to_idx"][user_id]
    scores = engine["model"].predict(
        uidx,
        engine["all_item_idx"],
        item_features=engine["item_features"],
    )

    # --- Sélection rapide des meilleurs candidats (sur-échantillonnage pour filtrer "seen")
    candidate_n = min(len(scores), k * 50)
    top_idx = np.argpartition(-scores, candidate_n)[:candidate_n]
    top_idx = top_idx[np.argsort(-scores[top_idx])]

    # --- Filtrage des items déjà vus + construction des recos
    seen = set(engine["user_seen"].get(user_id, []))
    recs: list[int] = []

    for ii in top_idx:
        aid = engine["idx_to_item"][int(ii)]
        if aid in seen:
            continue
        recs.append(int(aid))
        if len(recs) >= k:
            break

    # --- Fallback: compléter avec trending si pas assez de recos (ou trop d'items vus)
    if len(recs) < k:
        for aid in engine["trending"]:
            if aid not in seen and aid not in recs:
                recs.append(int(aid))
            if len(recs) >= k:
                break

    return recs, "lightfm_online"


# recommend: endpoint HTTP (parse params, charge engine, renvoie JSON).
@app.route(route="recommend", methods=["GET"])
def recommend(req: func.HttpRequest) -> func.HttpResponse:
    """
    Endpoint:
      GET /api/recommend?user_id=123&k=5
    Retour:
      {"user_id": 123, "recommended_articles": [...], "strategy": "lightfm_online|trending"}
    """
    global _ENGINE

    # --- Lecture et validation des paramètres d'entrée
    user_id_str = req.params.get("user_id")
    if not user_id_str:
        return func.HttpResponse("Missing query parameter 'user_id'", status_code=400)

    try:
        user_id = int(user_id_str)
    except ValueError:
        return func.HttpResponse("'user_id' must be an integer", status_code=400)

    # --- Chargement au cold start (une seule fois)
    if _ENGINE is None:
        logging.info("Cold start: loading engine from Blob...")
        try:
            _ENGINE = _load_engine_from_blob()
        except Exception as e:
            logging.exception("Failed to load engine from Blob")
            return func.HttpResponse(f"Engine load failed: {type(e).__name__}", status_code=500)

    # --- Paramètre k (fallback sur la valeur du modèle si invalide)
    try:
        k = int(req.params.get("k", _ENGINE["top_k"]))
    except ValueError:
        k = int(_ENGINE["top_k"])

    # --- Calcul des recommandations
    try:
        recos, strategy = _recommend(_ENGINE, user_id=user_id, k=k)
    except Exception as e:
        logging.exception("Recommendation failed")
        return func.HttpResponse(f"Recommend failed: {type(e).__name__}", status_code=500)

    # --- Construction de la réponse JSON
    payload = {"user_id": user_id, "recommended_articles": recos, "strategy": strategy}
    return func.HttpResponse(
        body=json.dumps(payload),
        mimetype="application/json",
        status_code=200,
    )
