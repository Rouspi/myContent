# app.py
# UI MVP: saisie user_id + appel Azure Function + affichage 5 recos.

import json

import requests
import streamlit as st

# --- Config
AZURE_ENDPOINT = "https://mycontentapp-27366.azurewebsites.net/api/recommend"
DEFAULT_USER_ID = 3004
DEFAULT_K = 5

st.set_page_config(page_title="MyContent — Reco MVP", layout="centered")
st.title("MyContent — MVP Recommandation")
st.caption("Saisis un user_id (ex: -1 => trending), appelle l'Azure Function, et affiche 5 articles recommandés.")


# --- Helper: appel API
def call_reco_api(user_id: int, k: int) -> dict:
    # Appel HTTP GET avec paramètres
    params = {"user_id": user_id, "k": k}
    r = requests.get(AZURE_ENDPOINT, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


# --- Entrée utilisateur
st.subheader("Entrée")

# Champ user_id (manuel)
user_id = st.number_input("user_id", value=DEFAULT_USER_ID, step=1)

# Champ k
k = st.number_input("k (nombre de recos)", min_value=1, max_value=20, value=DEFAULT_K, step=1)

# Bouton d'action
run = st.button("Recommander", type="primary")


# --- Appel API + affichage
if run:
    st.write("Endpoint:", AZURE_ENDPOINT)

    # Appel
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

    # Résultat
    st.success(f"OK — strategy = {out.get('strategy')}")
    st.subheader("Recommandations (IDs)")
    st.write(out.get("recommended_articles", []))

    with st.expander("Réponse JSON complète"):
        st.json(out)
