Azure Function App — Tests unitaires

Lancer les tests :

1) Se placer dans le dossier
   cd azure/function_app

2) Lancer les tests
   python -m unittest discover -s tests -v

Pré‑requis :
- Python 3.10+
- Dépendances :
  pip install -r requirements.txt

Accès en ligne :
- https://mycontentapp-27366.azurewebsites.net
- Endpoint : https://mycontentapp-27366.azurewebsites.net/api/recommend?user_id=123&k=5

Démarrer en local :
- Dans le dossier azure/function_app :
  func start

Notes:
- Les tests utilisent des mocks et ne téléchargent pas d'artefacts Azure.
- Assure-toi d'avoir les dépendances installées (requirements.txt).
