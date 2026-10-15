# Pour les prochaines équipes

[← Retour au README](../README.md)

**Démarrage en 10 minutes** : cloner, `uv sync`, `uv run pytest -q`, définir `OLLAMA_API_KEY` (et, pour Jira, les
trois variables `JIRA_*`), ouvrir un **nouveau** terminal, puis `uv run review-agent doctor` (tout doit afficher OK),
`uv run review-agent ui --open`, et lancer une revue sur `ebirdyx/shipping-demo#1` (ticket KAN-4) ou sur votre propre PR.

Documents utiles : `docs/evaluation-howto.md` (comment évaluer et comparer des configurations, de façon reproductible), `docs/findings-log.md`
(ce que nous avons appris en construisant l'agent), `docs/model-comparison-notes.md` (observations réelles par modèle), `docs/comparison-protocol.md`
(comment comparer avec Claude ou ChatGPT, sans clé d'API), `integration/code-review.yml` (workflow GitHub Actions).

À faire, dans l'ordre :

1. Lire le README et `docs/architecture.md`, puis `src/code_review_agent/schemas.py` (contrats) et `evaluation/scoring.py` (grille d'étiquetage).
2. Valider les réponses attendues et les étiquettes (`reviewed_by`).
3. Mesurer le pipeline multi-passes contre le pipeline simple (`--pipeline single`) et la vérification (`--no-verify`) sur le
   banc d'essai ; exécuter le *held-out* une seule fois, prompt figé (`--confirm-frozen`).
4. Essayer Qwen en local (Ollama) et comparer avec Claude / ChatGPT / Gemini **sur les mêmes cas et la même grille**.
5. Activer le workflow Actions sur un vrai dépôt (secrets, droits `pull-requests: write`) et observer les commentaires.
6. Vérifier la cohérence entre la liste des exigences et les constats (idée décrite dans `docs/model-comparison-notes.md`).
7. Ajouter d'autres connecteurs (GitLab, Bitbucket) derrière la même forme `ReviewInput`.
8. Pistes futures : extraits de code autour des modifications pour les gros fichiers, revue d'une branche locale non
   poussée, serveur MCP pour les éditeurs, affinage du modèle.

Pièges rencontrés : une variable d'environnement modifiée n'est vue que par un **nouveau** terminal ; une faute de frappe
dans `JIRA_BASE_URL` donne une erreur de certificat (la commande `doctor` l'explique) ; un serveur `review-agent ui`
ouvert verrouille `review-agent.exe` sous Windows (`uv sync` échoue tant qu'il tourne).
Si le point d'entrée change (déplacement de `cli.py`), arrêter l'interface puis relancer `uv sync` ; en attendant, `python -m code_review_agent` fonctionne toujours.

Un cas ajouté au banc d'essai : créer `evaluation/cases/<id>/` (`ticket.json`, `pr.json`, `change.diff`) et
`evaluation/expected/<id>.json`, l'ajouter à `evaluation/split.json`, puis `uv run pytest`.
`evaluation/scripts/author_cases.py` montre comment les cas actuels ont été générés (brouillon IA : à relire).
