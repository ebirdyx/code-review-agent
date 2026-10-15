# Utilisation : commandes, interface web, Jira, GitHub Actions

[← Retour au README](../README.md)

## Commandes

```bash
# 0. Interface web (voir la section plus bas)
uv run review-agent ui --open

# 1. Sans modèle
uv run review-agent build-context examples/free-shipping-faulty --out out/contexte.txt
uv run review-agent validate examples/free-shipping-faulty tests/fixtures/raw/malformed.txt

# 2. Avec un modèle : une revue sur un exemple local
uv run review-agent review examples/free-shipping-faulty

# 3. Avec une Pull Request GitHub (lecture seule)
uv run review-agent fetch-pr pallets/click#3884                  # télécharge seulement
uv run review-agent review-pr pallets/click#3884 --ticket mon-ticket.json   # télécharge puis révise
uv run review-agent fetch-ticket SHOP-1                           # vérifie la connexion Jira
uv run review-agent review-pr proprietaire/depot#12 --jira       # PR + ticket Jira lié

# 4. Évaluation
uv run review-agent eval-run --split dev --repeat 3 --label multi-full   # appelle le modèle ; enregistre la configuration (eval-config.json)
uv run review-agent eval-run --split dev --repeat 3 --pipeline single --label single-pass
uv run review-agent eval-compare runs/eval-single-pass-* runs/eval-multi-full-*   # compare les configurations côte à côte (sans modèle)
# Comparaison avec un agent plus avancé (Claude, ChatGPT...) utilisé dans un chat : voir docs/comparison-protocol.md
uv run review-agent eval-export --split dev --out out/chat-prompts                  # un fichier à coller dans un NOUVEAU chat par cas
uv run review-agent eval-import out/answers-claude --split dev --label claude-chat --model "<nom exact>" --lenient   # les réponses collées sont validées et notées comme celles des modèles ouverts
uv run review-agent eval-template runs/eval-dev-<horodatage>     # propose des étiquettes
uv run review-agent eval-score  runs/eval-dev-<horodatage> --labels evaluation/labels/<fichier>.json --split dev
uv run review-agent eval-revalidate runs/eval-dev-<horodatage>   # revalide sans rappeler le modèle
```

Chaque revue crée un dossier dans `runs/` : `run.json` (modèle, version du prompt, réglages,
révision revue, durées), `context.txt` (le texte exact envoyé), `raw_response.txt` (la réponse brute),
`result.json` (résultat validé) et `report.md` (rapport).
Une PR téléchargée est enregistrée comme dossier d'exemple dans `runs/pr-snapshots/` : on peut la
rejouer hors ligne avec `review`, à la révision exacte (`head_sha`) qui a été lue.

## Interface web locale

```bash
uv run review-agent ui --open        # http://127.0.0.1:8765/
```


- **Liste des revues** (en cours, terminées, échouées) qui se met à jour seule, **groupée** : les revues lancées seules (les 3 plus récentes, puis « show older reviews »)
  et un groupe repliable par dossier d'évaluation (`eval-run`, `eval-import`...). Le champ **Filter** cherche dans le cas, le modèle, l'état, le ticket et le nom du groupe.
- **Vue Evaluations** (bouton en haut de la liste) : un tableau des dossiers d'évaluation avec leur configuration enregistrée (pipeline, prompt, modèle, outils, contexte,
  vérificateur, répétitions) et leur résultat ; cocher 2 à 6 dossiers puis **Compare selected** affiche le même tableau que `review-agent eval-compare` (étiquettes provisoires
  signalées). Lien direct : `http://127.0.0.1:8765/#evaluations&compare=dossier1,dossier2`.
- Dans les constats : une pastille **requirement N not met** quand un constat vient d'un critère du ticket non respecté, et le panneau **Repository context** (appelants, tests,
  fonctions appelées) montré au modèle.
- **Lancer une revue** : saisir `proprietaire/depot#12`, cocher « Also read its Jira ticket » au besoin (un préfixe de ticket facultatif, par exemple `KAN`, aide à retrouver `KAN-4` dans le texte de la PR), puis « Review this PR ». La chronologie montre chaque étape en direct :
  lecture de la PR, lecture du ticket, construction du contexte, appel du modèle (durée, jetons), validation, rapport.
- **Rapport**, **constats** (avec preuves et problèmes de validation), **chronologie**, **réponse brute** du modèle.
- **Décision humaine** : chaque constat peut être *accepté* ou *rejeté* avec une note (dans l'interface : touches `j`/`k` pour naviguer, `a` accepter, `d` rejeter ; enregistrement automatique, bouton Annuler). Le résultat est enregistré dans `triage.json` et `report-triaged.md`
  (le rapport original n'est jamais modifié).

Le serveur n'écoute que sur `127.0.0.1`. Il refuse les requêtes dont l'hôte ou l'origine sont inattendus, exige un en-tête propre à l'interface pour toute écriture,
valide les noms de dossiers (pas de remontée de chemin) et applique une politique CSP stricte. La page n'insère jamais de texte du modèle, du ticket ou de la PR comme HTML.
La clé `OLLAMA_API_KEY` doit être définie dans le terminal où l'on lance `ui` (le modèle et l'adresse se règlent avec les mêmes options que `review`).

## Jira

1. Créer un site gratuit (Jira Free, jusqu'à 10 utilisateurs) et un projet, par exemple la clé `SHOP`.
2. Créer un ticket avec une description et des critères d'acceptation. Deux façons sont reconnues :
   un champ nommé « Acceptance Criteria » (ou « Critères d'acceptation »), **ou** une section de la description
   intitulée « Acceptance criteria » suivie d'une liste. L'outil indique d'où viennent les critères.
3. Créer un jeton d'API et définir `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` (voir Configuration).
4. Vérifier : `uv run review-agent doctor` teste d'un coup le modèle (clé présente), Jira (« connecté en tant que … »),
   GitHub (accès et requêtes restantes) et les outils d'analyse statique, sans jamais afficher un secret. Une faute de
   frappe dans le nom du site Jira est signalée explicitement. Puis `uv run review-agent fetch-ticket SHOP-1` affiche le
   titre, le nombre de critères et leur provenance. **Ouvrir un nouveau terminal après avoir modifié une variable
   d'environnement** : les terminaux déjà ouverts gardent l'ancienne valeur.
5. Lier la PR au ticket. **Convention** : une ligne `Jira: SHOP-1` (ou `Jira: SHOP-1, SHOP-2`) dans la description de la PR,
   ou un titre qui commence par `SHOP-1:` ou `[SHOP-1]`. Avec `JIRA_PROJECTS=SHOP`, toute clé de ce projet dans le titre ou la
   description est reconnue. Sans liste de projets, seuls les liens explicites comptent (pour ne pas prendre « UTF-8 » pour un ticket).
6. Lancer : `uv run review-agent review-pr proprietaire/depot#12 --jira`.

Cas particuliers, tous signalés dans le rapport et jamais devinés : aucun lien trouvé, ticket introuvable ou inaccessible,
critères d'acceptation absents, plusieurs tickets (combinés, chaque critère préfixé de sa clé, 5 tickets au maximum).
`--ticket fichier.json` fournit un ticket à la main et remplace Jira.

## Intégration GitHub Actions et commentaire sur la PR

Le projet à relire appelle lui-même l'agent : le modèle `integration/code-review.yml` se copie dans
`.github/workflows/code-review.yml`. À chaque ouverture ou mise à jour d'une PR, il lance `review-pr … --post-comment` et
publie **un seul commentaire**, mis à jour à chaque push (repéré par un marqueur HTML caché), avec la liste des critères
(MET / NOT MET), les constats triés par gravité et l'avertissement habituel. Le rapport complet est joint au run en artefact.

- Secrets à créer dans le dépôt : `OLLAMA_API_KEY` (ou la clé du profil choisi) et, facultatifs, `JIRA_BASE_URL`, `JIRA_EMAIL`,
  `JIRA_API_TOKEN`. Variables facultatives : `REVIEW_AGENT_PROFILE`, `JIRA_PROJECTS`.
- Sécurité : droits minimaux (`contents: read`, `pull-requests: write`), déclencheur `pull_request` (jamais
  `pull_request_target`), PR venant d'un fork et brouillons ignorés, valeurs non fiables transmises par variables
  d'environnement. L'agent ne modifie jamais le code, n'approuve ni ne bloque une fusion : l'humain décide.
- Le texte du modèle est considéré comme non fiable : dans le commentaire, les `@mentions` sont neutralisées, le HTML, les
  liens et les images sont désactivés, les citations sont dans des blocs de code.
- Essai à blanc en local : `review-agent review-pr proprietaire/depot#12 --jira` écrit `comment.md` dans le dossier du run
  sans rien publier ; `--post-comment` (avec `GITHUB_TOKEN`) publie. Une revue en échec est publiée comme telle (« n'a pas
  abouti »), jamais comme une PR propre.
