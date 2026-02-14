# app.py
# Mini interface MVP: sélection d'un user_id + appel Azure Function + affichage des 5 recos.

import json
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

# --- Config
AZURE_ENDPOINT = "https://mycontentapp-27366.azurewebsites.net/api/recommend"
DEFAULT_K = 5

st.set_page_config(page_title="MyContent — Reco MVP", layout="centered")
st.title("MyContent — MVP Recommandation")
st.caption("Sélectionne un user_id, appelle l'Azure Function, et affiche 5 articles recommandés.")


# --- Helpers
def load_user_ids_from_csv(csv_path: str, col: str = "user_id", max_users: int = 2000) -> list[int]:
    """Charge des user_id uniques depuis un CSV local (ex: clicks_sample.csv ou un export)."""
    p = Path(csv_path)
    if not p.exists():
        return []
    df = pd.read_csv(p)
    if col not in df.columns:
        return []
    user_ids = (
        df[col]
        .dropna()
        .astype(int)
        .drop_duplicates()
        .head(max_users)
        .tolist()
    )
    return user_ids


def call_reco_api(user_id: int, k: int) -> dict:
    """Appelle l'Azure Function et renvoie le JSON."""
    params = {"user_id": user_id, "k": k}
    r = requests.get(AZURE_ENDPOINT, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# --- Sidebar: source des users
st.sidebar.header("Source des user_id")

use_csv = st.sidebar.checkbox("Charger les user_id depuis un CSV local", value=True)
csv_path = st.sidebar.text_input("Chemin du CSV", value="clicks_sample.csv")
csv_col = st.sidebar.text_input("Nom de la colonne user_id", value="user_id")

user_ids: list[int] = []
if use_csv:
    user_ids = load_user_ids_from_csv(csv_path, col=csv_col, max_users=5000)

if not user_ids:
    st.sidebar.warning(
        "Aucun user_id trouvé via CSV. "
        "Tu peux soit corriger le chemin/colonne, soit saisir un user_id à la main."
    )

st.sidebar.markdown("---")

# --- UI principale
k = st.number_input("Nombre de recommandations (k)", min_value=1, max_value=20, value=DEFAULT_K, step=1)

col1, col2 = st.columns([2, 1])

with col1:
    if user_ids:
        user_id = st.selectbox("Choisis un user_id", user_ids, index=0)
    else:
        user_id = st.number_input("Saisis un user_id", min_value=-1, value=3004, step=1)

with col2:
    run = st.button("Recommander", type="primary")

# --- Appel API
if run:
    st.write("Appel API:", AZURE_ENDPOINT)
    with st.spinner("Calcul des recommandations..."):
        try:
            out = call_reco_api(int(user_id), int(k))
        except requests.HTTPError as e:
            st.error(f"Erreur HTTP: {e}")
            st.stop()
        except requests.RequestException as e:
            st.error(f"Erreur réseau: {e}")
            st.stop()
        except json.JSONDecodeError:
            st.error("Réponse non-JSON reçue.")
            st.stop()

    # --- Affichage
    st.success(f"OK — strategy = {out.get('strategy')}")
    recos = out.get("recommended_articles", [])

    st.subheader("Top recommandations")
    if recos:
        st.write(recos)
    else:
        st.info("Aucune recommandation retournée.")

    with st.expander("Réponse brute"):
        st.json(out)
