# MyContentUI — Application Streamlit

**Description (1 phrase)** :
Interface web Streamlit qui appelle l'API de recommandation et affiche les articles recommandés pour un user_id.

## URL en ligne
- `https://mycontentui.streamlit.app`

## API utilisée
- `https://mycontentapp-27366.azurewebsites.net/api/recommend`

## Utilisation

1. Installer les dépendances :

```bash
pip install -r requirements.txt
```

2. Lancer l'application :

```bash
streamlit run app.py
```

## Notes
- Assure-toi que l'API Azure est accessible (URL dans `app.py` ou variables d'environnement si configurées).
