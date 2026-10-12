# Agent de revue de code : Pull Request vs exigences du ticket

Prototype d'agent d'assistance à la revue de code (projet de session MGL805, ÉTS).
L'agent lit une Pull Request (diff + description) et les exigences d'un ticket, interroge un
modèle de langage **à poids ouverts** via Ollama, puis produit des constats structurés
(fichier, ligne, preuves citées) dans un rapport JSON et Markdown.

> **Le réviseur humain garde la décision finale.** L'outil ne fusionne rien, ne publie rien
> et ne modifie jamais un dépôt : l'accès à GitHub est en lecture seule.

## État du projet

| Fonction | État |
|---|---|
| Entrées locales (ticket JSON + diff) | Fait, testé |
| Contexte pour le modèle (instructions séparées du contenu non fiable, diff numéroté, budget de taille) | Fait, testé |
| Appel d'un modèle Ollama (cloud ou local) | Fait, testé (modèle réel : `gpt-oss:120b`) |
| Validation de la sortie (JSON, schéma, fichier, ligne, citations, doublons) | Fait, testé |
| Rapports JSON et Markdown | Fait, testé |
| Banc d'essai (22 cas Python, séparation dev / hold-out, précision, rappel, F1) | Fait. **Étiquettes à valider par un humain** |
| Suivi en direct (événements dans le terminal et `events.jsonl`) et interface web locale (liste des revues, rapport, constats, chronologie, accepter / rejeter chaque constat, lancer une revue de PR) | Fait, testé (serveur réel en local, page vérifiée dans un vrai navigateur) |
| Lecture d'une Pull Request GitHub (lecture seule, révision exacte enregistrée) | Fait, testé avec simulation et avec l'API réelle (lecture seulement) |
| Revue d'une PR GitHub + ticket Jira liée, par le modèle | Fait et exécuté pour de vrai (PR `ebirdyx/shipping-demo#1` + `KAN-4`, `gpt-oss:120b`) : voir `evaluation/results/real-pr-demo/` |
| Tickets Jira (lecture seule, lien PR → ticket, critères d'acceptation, tickets multiples ou indisponibles) | Fait. Testé avec simulation **et sur un vrai site Jira Cloud** (`fetch-ticket KAN-4` : critères lus dans la section de la description). Le cas « champ personnalisé » n'a été testé qu'avec simulation |
| GitHub Actions / publication de commentaires | **À faire** |
| Comparaison avec Claude / Gemini | **À faire** |
| Banc d'essai sur un modèle local libre (Qwen2.5-Coder, etc.) | **À faire** (l'outil le permet déjà) |

## Architecture et responsabilités

```
ticket.json  pr.json  change.diff  supporting/        (ou une PR GitHub téléchargée)
        \        |        |          /
         v       v        v         v
   loading.py / github.py     lecture des entrées, instantané d'une PR
              |
         context.py           assemble le message : instructions (de confiance) + contenu non fiable
              |
       model_client.py        seul module qui parle au modèle (Ollama via LangChain)
              |
         review.py            exécute un appel, enregistre tout dans run.json
              |
       validation.py          JSON, schéma, fichier/ligne/citations, doublons -> ReviewResult
              |
          report.py           rapport Markdown lisible
```

| Module | Rôle |
|---|---|
| `schemas.py` | Contrats de données (Pydantic) : ticket, entrée, constat, résultat. |
| `context.py` | Construit le contexte. Les instructions (`prompts/review_vN.md`) sont séparées du contenu non fiable, encadré de marqueurs. Le diff reçoit des numéros de ligne. Ce qui manque ou ne tient pas dans le budget est **signalé**, jamais tronqué en silence. |
| `model_client.py` | Adresse, modèle, délai, température, graine configurables. Erreurs classées (connexion, délai, clé, quota, modèle introuvable). |
| `review.py` | Un appel au modèle. Conserve la réponse brute, le modèle, la version du prompt, les réglages, la révision revue. |
| `validation.py` | Rejette un JSON invalide ou hors schéma. Vérifie que fichier, ligne et citations existent dans l'entrée. **Ne corrige jamais une localisation** : elle est signalée. |
| `report.py` | Rapport Markdown. Un échec de revue n'est jamais présenté comme « aucun constat ». |
| `github.py` | Lecture seule d'une PR : pagination, patchs absents, PR trop grande, vérification que la PR n'a pas changé pendant la lecture. |
| `evaluation.py` | Étiquetage humain, précision, rappel, F1, exactitude de la ligne et de la catégorie. |

### Ce que la validation prouve (et ne prouve pas)

La validation vérifie que le fichier, la ligne et les citations **existent** dans ce que le modèle a reçu.
Elle ne prouve pas qu'un constat est **vrai** : un constat peut citer une vraie ligne et tirer une fausse conclusion.
C'est le rôle du réviseur humain, et de l'étiquetage manuel dans l'évaluation.

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/) (gère Python 3.12 automatiquement) et Git.

```bash
git clone https://github.com/ebirdyx/code-review-agent.git
cd code-review-agent
uv sync
uv run pytest -q          # 260+ tests, aucun ne nécessite de modèle ni de réseau
uv run review-agent check-examples
```

Versions utilisées (voir aussi `uv.lock`) : Python 3.12.10, pydantic 2.13.5, langchain-ollama 1.1.0, httpx 0.28.1.

## Configuration du modèle

L'adresse, le modèle, le délai, etc. se règlent par options (`--host`, `--model`, `--timeout`,
`--temperature`, `--seed`, `--num-ctx`, `--prompt-version`) ou par variables d'environnement.

| Variable | Rôle |
|---|---|
| `OLLAMA_API_KEY` | Clé pour Ollama Cloud (https://ollama.com/settings/keys). **Ne jamais la mettre dans le dépôt.** |
| `OLLAMA_HOST` | Adresse du serveur (par défaut `https://ollama.com`) |
| `OLLAMA_MODEL` | Modèle (par défaut `gpt-oss:120b`) |
| `OLLAMA_TIMEOUT` | Délai en secondes (par défaut 180) |
| `GITHUB_TOKEN` | Optionnel. Sans jeton : 60 requêtes/heure et dépôts publics seulement. |
| `JIRA_BASE_URL` | Adresse du site Jira, par exemple `https://monequipe.atlassian.net` |
| `JIRA_EMAIL` | Courriel du compte Atlassian |
| `JIRA_API_TOKEN` | Jeton d'API Atlassian (https://id.atlassian.com/manage-profile/security/api-tokens). **Jamais dans le dépôt.** |
| `JIRA_ACCEPTANCE_FIELD` | Optionnel. Identifiant (`customfield_10042`) ou nom du champ des critères d'acceptation |
| `JIRA_PROJECTS` | Optionnel. Clés de projets, par exemple `SHOP,APP`, pour repérer les tickets dans les PR |

Définir la clé de façon permanente sous Windows (PowerShell), puis ouvrir un **nouveau** terminal :

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_API_KEY", "votre-cle", "User")
```

### Utiliser un modèle local (recommandé pour la reproductibilité)

```bash
ollama pull qwen2.5-coder:14b
uv run review-agent review examples/free-shipping-faulty --host http://localhost:11434 --model qwen2.5-coder:14b
```

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
uv run review-agent eval-run --split dev --repeat 3              # appelle le modèle
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

- **Liste des revues** (en cours, terminées, échouées) qui se met à jour seule.
- **Lancer une revue** : saisir `proprietaire/depot#12`, cocher « Jira ticket » au besoin, puis « Review this PR ». La chronologie montre chaque étape en direct :
  lecture de la PR, lecture du ticket, construction du contexte, appel du modèle (durée, jetons), validation, rapport.
- **Rapport**, **constats** (avec preuves et problèmes de validation), **chronologie**, **réponse brute** du modèle.
- **Décision humaine** : chaque constat peut être *accepté* ou *rejeté* avec une note. Le résultat est enregistré dans `triage.json` et `report-triaged.md`
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
4. Vérifier : `uv run review-agent fetch-ticket SHOP-1` affiche le titre, le nombre de critères et leur provenance.
5. Lier la PR au ticket. **Convention** : une ligne `Jira: SHOP-1` (ou `Jira: SHOP-1, SHOP-2`) dans la description de la PR,
   ou un titre qui commence par `SHOP-1:` ou `[SHOP-1]`. Avec `JIRA_PROJECTS=SHOP`, toute clé de ce projet dans le titre ou la
   description est reconnue. Sans liste de projets, seuls les liens explicites comptent (pour ne pas prendre « UTF-8 » pour un ticket).
6. Lancer : `uv run review-agent review-pr proprietaire/depot#12 --jira`.

Cas particuliers, tous signalés dans le rapport et jamais devinés : aucun lien trouvé, ticket introuvable ou inaccessible,
critères d'acceptation absents, plusieurs tickets (combinés, chaque critère préfixé de sa clé, 5 tickets au maximum).
`--ticket fichier.json` fournit un ticket à la main et remplace Jira.

## Méthode d'évaluation

- **Cas** : `evaluation/cases/` (19 cas Python) et `examples/` (3 cas), répartis en boundary, logic, requirement,
  error_handling, security, correct, plus un cas d'injection de prompt dans le ticket.
- **Réponses attendues** : `evaluation/expected/`, écrites à la main, **jamais dans les prompts** (un test le vérifie).
  Chaque défaut attendu a une ligne calculée à partir d'un extrait de code (`code_anchor`), vérifiée par test.
- **Séparation** : `evaluation/split.json`. *dev* (9 cas) sert à améliorer le prompt ; *heldout* (13 cas) ne se lance
  qu'une fois le prompt figé (`--confirm-frozen`).
- **Étiquettes** (grille écrite avant les résultats, voir `evaluation.py`) : `tp`, `fp`, `duplicate` (compté une fois), `extra`
  (observation plausible hors réponses attendues, non comptée dans la précision). Une catégorie différente reste un `tp`.
  Une réserve hypothétique sur une règle non spécifiée (« si l'entreprise voulait… ») est un `fp`.
- **Mesures** : TP/FP/FN, précision, rappel, F1, exactitude de la ligne et de la catégorie, utilité (0 à 2), durée, jetons.
  Le coût d'inférence n'est **pas mesuré** (Ollama Cloud ne le renvoie pas).
- Un tableau reste **PROVISOIRE** tant que `reviewed_by` (nom d'une personne) est vide dans le fichier d'étiquettes.

### Résultats préliminaires (ensemble *dev*, `gpt-oss:120b`, prompt `review_v1`, 27 exécutions)

Étiquettes provisoires (brouillon IA, à confirmer par un humain). Les cas *dev* sont simples : ces chiffres ne
prédisent pas la performance sur *heldout*.

| TP | FP | FN | Précision | Rappel | F1 | Ligne exacte | Catégorie attendue |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 18 | 1 | 0 | 0,95 | 1,00 | 0,97 | 14/18 | 12/18 |

Détail : `evaluation/results/dev-eval1.md`.

## Limites connues

- Le modèle n'est pas déterministe, même à température 0 : répéter les exécutions (`--repeat`).
- Petit échantillon : 6 défauts sur *dev*. Les résultats sont indicatifs, pas statistiques.
- Le budget de contexte est en **caractères**, pas en jetons. Les très gros fichiers ne sont pas fournis en entier (signalé dans le rapport).
- Défense contre l'injection de prompt partielle (marqueurs + consigne) : un modèle peut encore être trompé.
- `gpt-oss:120b` sur Ollama Cloud est un service hébergé, limité et susceptible de changer. Pour la reproductibilité,
  comparer avec un modèle local.
- Le connecteur Jira a été validé sur un seul site réel (Jira Cloud gratuit, un ticket). Les champs personnalisés de critères
  d'acceptation, les jetons à portée limitée et les tickets multiples n'ont été testés qu'avec des réponses simulées.
- Pas d'intégration continue, pas de publication de commentaires pour l'instant.

## Licences

| Élément | Licence |
|---|---|
| Ce logiciel | MIT (voir `LICENSE`) — à confirmer par l'équipe |
| `gpt-oss` (poids ouverts) | Apache-2.0 (vérifié sur les pages Hugging Face et Ollama) |
| Qwen2.5-Coder 14B / 32B | Apache-2.0 (vérifié sur les pages Hugging Face) |
| Rapport d'équipe | À décider |

Ollama Cloud est un **service** : l'utiliser a des limites d'usage (palier gratuit), et le code envoyé quitte la machine.
N'y envoyez pas de code confidentiel.

## Pour les prochaines équipes

1. Lire ce fichier, puis `src/code_review_agent/schemas.py` (contrats) et `evaluation.py` (grille d'étiquetage).
2. Valider les réponses attendues et les étiquettes (`reviewed_by`).
3. Exécuter le banc d'essai avec un modèle local, puis avec Claude ou Gemini, **sur les mêmes cas et la même grille**.
4. Tester le connecteur Jira sur un vrai site et l'adapter (champ des critères, éventuel jeton à portée limitée).
5. Ajouter GitHub Actions, puis la publication de commentaires comme fonction **séparée et configurable**.
6. Ajouter d'autres connecteurs (GitLab, Bitbucket) derrière la même forme `ReviewInput`.
7. Pistes futures : extraits de code autour des modifications pour les gros fichiers, agents spécialisés, RAG, affinage du modèle.

Un cas ajouté au banc d'essai : créer `evaluation/cases/<id>/` (`ticket.json`, `pr.json`, `change.diff`) et
`evaluation/expected/<id>.json`, l'ajouter à `evaluation/split.json`, puis `uv run pytest`.
`evaluation/author_cases.py` montre comment les cas actuels ont été générés (brouillon IA : à relire).
