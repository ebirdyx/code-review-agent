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
| **Pipeline multi-passes** (par défaut) : 3 spécialistes (conformité au ticket critère par critère, défauts, sécurité), fusion des doublons, puis passe de **vérification** qui peut écarter un constat (toujours visible, avec la raison) | Fait, testé (352 tests dont une exécution réelle avec `gpt-oss:120b`). **Qualité pas encore mesurée** sur le banc d'essai |
| **Analyse statique** (Ruff + Bandit, Python) : avertissements déterministes sur les lignes modifiées, fusionnés avec les constats du modèle et fournis aux passes comme pistes | Fait, testé avec les vrais outils et sur une vraie PR (pallets/click) |
| **Règles d'équipe** (`.review-agent/rules.md` lu sur la branche de base, ou `--rules`) vérifiées par une passe dédiée | Fait, testé (modèle simulé) et sur 4 exécutions réelles |
| **Profil du changement** (taille, tests modifiés ou non, zones sensibles, dépendances, CI), sans modèle | Fait, testé |
| **Contexte du dépôt** (graphe de code léger, Python) : pour chaque fonction modifiée, ses appelants, les fonctions qu'elle appelle, les tests qui la mentionnent et le constructeur de sa classe, trouvés avec `ast` dans une seule archive téléchargée | Fait, testé (simulation) et essayé sur les PR de démonstration. Effet **mesuré sur 6 PR seulement** : voir `evaluation/results/context-ablation/` |
| **Profils de modèles** (`--profile`) : Ollama local ou cloud, Qwen2.5-Coder via un service hébergé compatible OpenAI (OpenRouter) | Fait. **Exécutions réelles** de Qwen2.5-Coder 32B et Qwen3-Coder 30B via OpenRouter sur la PR de démonstration (voir `docs/model-comparison-notes.md`). Qwen local (Ollama) **pas encore exécuté** |
| Suivi en direct (événements dans le terminal et `events.jsonl`) et interface web locale (liste des revues, rapport, constats, chronologie, accepter / rejeter chaque constat, lancer une revue de PR) | Fait, testé (serveur réel en local, page vérifiée dans un vrai navigateur) |
| Lecture d'une Pull Request GitHub (lecture seule, révision exacte enregistrée) | Fait, testé avec simulation et avec l'API réelle (lecture seulement) |
| Revue d'une PR GitHub + ticket Jira liée, par le modèle | Fait et exécuté pour de vrai (PR `ebirdyx/shipping-demo#1` + `KAN-4`, `gpt-oss:120b`) : voir `evaluation/results/real-pr-demo/` |
| Tickets Jira (lecture seule, lien PR → ticket, critères d'acceptation, tickets multiples ou indisponibles) | Fait. Testé avec simulation **et sur un vrai site Jira Cloud** (`fetch-ticket KAN-4` : critères lus dans la section de la description). Le cas « champ personnalisé » n'a été testé qu'avec simulation |
| Commentaire unique et auto-mis à jour sur la PR (`--post-comment`) et modèle de workflow GitHub Actions (`integration/code-review.yml`) | Fait et testé (simulation). **Pas encore actif sur un vrai dépôt** : voir « Intégration GitHub Actions » |
| Comparaison avec Claude / ChatGPT / Gemini | **À faire** : protocole dans `docs/comparison-protocol.md` |
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
| `model_client.py` | Deux clients derrière la même interface : Ollama et API compatible OpenAI (via LangChain). Adresse, modèle, délai, température, graine configurables. Erreurs classées (connexion, délai, clé, quota, crédit, modèle introuvable). |
| `profiles.py`, `models.toml` | Profils de modèles nommés et documentés (aucun secret). |
| `pipeline.py` | Pipeline multi-passes : exécution des spécialistes, fusion, vérification, assemblage pur du résultat. |
| `evidence.py` | Analyse statique (Ruff, Bandit) en bac à sable, correspondance avec les lignes modifiées, profil du changement. |
| `service.py`, `events.py` | Le flux de travail partagé par la ligne de commande et l'interface web, et les événements de progression. |
| `ui.py`, `web/` | Interface web locale. |
| `review.py` | Un appel au modèle. Conserve la réponse brute, le modèle, la version du prompt, les réglages, la révision revue. |
| `validation.py` | Rejette un JSON invalide ou hors schéma. Vérifie que fichier, ligne et citations existent dans l'entrée. **Ne corrige jamais une localisation** : elle est signalée. |
| `report.py` | Rapport Markdown. Un échec de revue n'est jamais présenté comme « aucun constat ». |
| `github.py` | Lecture seule d'une PR : pagination, patchs absents, PR trop grande, vérification que la PR n'a pas changé pendant la lecture. |
| `evaluation.py` | Étiquetage humain, précision, rappel, F1, exactitude de la ligne et de la catégorie. |

### Pipeline multi-passes

Un petit modèle réussit mieux une tâche étroite que « tout relire ». Chaque revue lance donc des spécialistes avec le même contenu mais des consignes différentes :

| Passe | Rôle | Sortie |
|---|---|---|
| `compliance` | Compare le code à **chaque critère d'acceptation** du ticket (ignorée sans ticket ni critères) | Un verdict par critère : *met*, *not met* ou *cannot determine*, avec preuves citées |
| `standards` | Compare les lignes ajoutées aux **règles d'équipe** (ignorée sans fichier de règles) | Constats citant la règle et le code |
| `defects` | Erreurs de logique, cas limites, gestion d'erreurs, maintenabilité | Constats |
| `security` | Vulnérabilités concrètes introduites par le changement | Constats |
| `verify` | Deuxième regard indépendant sur chaque constat candidat | *supported*, *uncertain* ou *unsupported* (écarté, mais **affiché** avec la raison) |

La fusion regroupe les signalements d'un même problème (même fichier et même ligne, catégories compatibles) en gardant la catégorie la plus précise, la gravité la plus haute et toutes les preuves.
Une passe qui échoue ou renvoie une réponse inutilisable est signalée (couverture partielle) sans bloquer les autres ; si **toutes** échouent, la revue est « échouée », jamais « aucun constat ».
Les passes tournent en parallèle dans la limite du fournisseur (`max_concurrency` du profil ; 1 pour le palier gratuit d'Ollama Cloud).
L'assemblage du résultat est une fonction **pure** des réponses enregistrées : `eval-revalidate` peut le refaire sans rappeler le modèle.
`--pipeline single` conserve l'ancien mode (un seul appel), utilisé pour les premiers résultats d'évaluation.
Options : `--passes defects,security`, `--no-verify`, `--verifier-profile NOM` (un autre modèle pour la vérification),
`--tools ruff,bandit` / `--no-tools`, `--ruff-select F,E9,B`, `--rules fichier.md`.
Coût : environ 4 fois plus de jetons qu'une seule passe (mesuré : 8171 en entrée / 1910 en sortie contre environ 1900 / 500).

### Preuves sans modèle : analyse statique, règles d'équipe, profil du changement

**Analyse statique.** Avant les passes, [Ruff](https://docs.astral.sh/ruff/) (familles F, E9, B, BLE, PLE, PLW) et [Bandit](https://bandit.readthedocs.io/) analysent les fichiers Python modifiés,
téléchargés en entier à la révision revue (le modèle, lui, ne voit que les petits fichiers). Les outils **lisent** le code sans l'exécuter, dans un dossier temporaire, sans shell,
avec un délai maximal, sans lire la configuration de la PR et sans aucune variable d'environnement qui ressemble à un secret.

- Un avertissement sur une ligne **ajoutée ou modifiée** par la PR devient un constat (`source = tool`, preuve = la ligne de code). Il n'est pas soumis au vote du vérificateur.
- Tous ces avertissements sont aussi donnés aux passes comme **pistes à vérifier** (« une piste n'est pas un verdict »).
- Les avertissements sur des lignes que la PR n'a pas touchées sont comptés mais jamais imputés à la PR.
- Contre le bruit : les avertissements de Bandit dans les fichiers de test sont ignorés (mesuré sur la PR réelle pallets/click#3884 : 270 des 276 avertissements étaient des `assert` de tests),
  et au plus 30 constats d'outils sont rapportés par revue, les plus graves d'abord, avec une note si d'autres ont été laissés de côté.
- Un outil qui échoue, expire ou ne trouve aucun fichier est signalé (tableau « Automated checks »), jamais ignoré en silence.
- Mesure sur nos cas synthétiques : sur 16 défauts introduits, Ruff et Bandit en signalent **4** sur la bonne ligne (injection SQL, MD5, `except Exception`, `urlopen`) et aucun sur les 3 changements corrects ;
  ils ne voient aucun des défauts de logique, de limite ou d'exigence. Les deux approches sont donc complémentaires.

**Règles d'équipe.** Un fichier de règles (voir `examples/review-rules.md`) est lu sur la **branche de base** de la PR (une PR ne peut pas réécrire ses propres règles) :
`.review-agent/rules.md`, sinon `review-rules.md`. En local : `--rules fichier.md`. La passe `standards` compare les lignes ajoutées à chaque règle et cite la règle mot pour mot.
Sans règles, la passe est ignorée et le rapport le dit.

**Profil du changement.** Sans modèle : fichiers, lignes, types, « du code source a changé mais aucun test », zones sensibles (auth, paiement, migrations…), dépendances, CI, taille.

**Contexte du dépôt (graphe de code léger).** Le diff montre ce qui change, pas comment le code est utilisé. Pour chaque fonction Python
modifiée, `codegraph.py` retrouve (avec le module standard `ast`, sans base vectorielle) : les fonctions qui l'appellent, celles qu'elle appelle,
les tests qui la mentionnent et le `__init__` de sa classe, plus des faits simples (« mentionnée dans aucun test »). Le dépôt est téléchargé en
**une seule archive** (2 requêtes, la limite de 60 requêtes par heure n'est donc pas consommée par fichier), lue en mémoire ; le jeton n'est jamais
envoyé au serveur de téléchargement. Le résultat est enregistré avec la capture de la PR (`related.json`), de sorte qu'une revue rejouée est identique.
Les appels sont trouvés **par nom** : un extrait peut désigner la mauvaise fonction (le modèle en est informé et les noms trop fréquents sont ignorés).
Les constats peuvent citer ces extraits (lignes et citations vérifiées comme pour le diff). `--no-context` désactive la fonction.
C'est notre équivalent du « rayon d'impact » d'outils comme Qodo.

**Sortie du modèle partiellement invalide.** Si un constat est mal formé (par exemple une étiquette de preuve inconnue), les constats valides sont **conservés** et le constat rejeté est signalé
(couverture partielle). Si tous les éléments sont invalides, la passe échoue.

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
uv run pytest -q          # 440+ tests, aucun ne nécessite de modèle ni de réseau (Ruff et Bandit réels, modèle et GitHub simulés)
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

### Profils de modèles

`uv run review-agent profiles` liste les profils (fournisseur, modèle, licence des poids, clé définie ou non, requêtes parallèles). Le fichier `src/code_review_agent/models.toml` contient :

| Profil | Modèle | Où | Licence des poids |
|---|---|---|---|
| `gpt-oss-cloud` (défaut) | gpt-oss:120b | Ollama Cloud (palier gratuit) | Apache-2.0 |
| `qwen25-coder-14b-local` | Qwen2.5-Coder 14B (modèle du plan d'équipe) | Ollama local | Apache-2.0 |
| `qwen25-coder-7b-local` | Qwen2.5-Coder 7B | Ollama local | Apache-2.0 |
| `qwen25-coder-32b-openrouter` | Qwen2.5-Coder 32B | OpenRouter (hébergé, payant à l'usage) | Apache-2.0 |
| `qwen3-coder-30b-openrouter` | Qwen3-Coder 30B-A3B | OpenRouter (hébergé) | Apache-2.0 |

On choisit avec `--profile NOM` ou `REVIEW_AGENT_PROFILE=NOM`. Pour ajouter un modèle : un fichier `models.toml` dans le dossier courant (fusionné par-dessus) ; aucune clé n'y est écrite, seulement le **nom** de la variable d'environnement qui la contient.
Les prix d'OpenRouter (environ 0,66 $ / 1,00 $ par million de jetons pour Qwen2.5-Coder 32B) viennent du catalogue public d'OpenRouter en octobre 2026 : à revérifier. Coût **mesuré** sur une PR de 2 lignes (9 000 jetons
en entrée pour toute la revue multi-passes) : environ 0,006 $ avec Qwen2.5-Coder 32B et 0,001 $ avec Qwen3-Coder 30B.
**Gratuit** : `gpt-oss:120b` sur le palier gratuit d'Ollama Cloud (limité) ou Qwen en local avec Ollama. Les exécutions Qwen
de l'équipe ont utilisé OpenRouter (quelques fractions de cent par revue), car le modèle local n'a pas encore été essayé.

**Qwen hébergé** : créer un compte et une clé sur openrouter.ai, la définir (`OPENROUTER_API_KEY`), puis
`uv run review-agent review-pr proprietaire/depot#12 --jira --profile qwen25-coder-32b-openrouter`.
**Confidentialité** : avec un profil hébergé (Ollama Cloud, OpenRouter), le diff, les fichiers modifiés et le ticket sont
envoyés à un tiers (OpenRouter les transmet en plus au fournisseur qui sert le modèle). Seul un modèle **local** garde le code
sur la machine. Ne pas utiliser un profil hébergé sur du code confidentiel (employeur, client) : voir
`docs/model-comparison-notes.md`.

### Utiliser un modèle local (recommandé pour la reproductibilité)

```bash
ollama pull qwen2.5-coder:14b
uv run review-agent review examples/free-shipping-faulty --profile qwen25-coder-14b-local
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

- Le vérificateur a **confirmé tous les constats candidats** dans nos 4 exécutions réelles : son utilité reste à prouver (comparer avec `--no-verify` sur le banc d'essai).
  Un accord entre deux appels du même modèle n'est pas une preuve d'exactitude.
- Un même défaut peut apparaître sous plusieurs catégories sur la même ligne (par exemple une injection SQL vue par la sécurité, par les défauts et par une règle d'équipe) : ils ne sont fusionnés que si leurs catégories sont compatibles.
- La passe `standards` peut être pointilleuse (elle a jugé qu'un docstring ne « disait pas ce que la fonction retourne »).
- L'analyse statique ne couvre que Python pour l'instant, et seulement les fichiers modifiés disponibles en entier (limite de 500 000 caractères par fichier).
  Le banc d'essai (22 cas) est aussi 100 % Python : la qualité sur TypeScript, Java, etc. n'a **pas été mesurée** (les passes du modèle lisent le diff
  et fonctionnent sans analyse statique, mais sans mesure on ne peut rien affirmer).
- Le contexte du dépôt n'a pas montré d'effet mesurable sur les 6 PR de démonstration (les défauts y sont visibles dans le diff) : il faut des cas où le défaut
  n'apparaît qu'avec le code environnant. Il ajoute environ 14 % de jetons en entrée. Appels trouvés par nom (peuvent désigner la mauvaise fonction), Python seulement.
- Le pipeline multi-passes (défaut) **n'a pas encore été évalué** sur le banc d'essai : tous les résultats chiffrés ci-dessous viennent du pipeline à une seule passe (`--pipeline single`).
  La vérification peut aussi écarter à tort un vrai constat (il reste visible dans « Dismissed by verification »).
- Le modèle n'est pas déterministe, même à température 0 : répéter les exécutions (`--repeat`).
- Petit échantillon : 6 défauts sur *dev*. Les résultats sont indicatifs, pas statistiques.
- Le budget de contexte est en **caractères**, pas en jetons. Les très gros fichiers ne sont pas fournis en entier (signalé dans le rapport).
- Défense contre l'injection de prompt partielle (marqueurs + consigne) : un modèle peut encore être trompé.
- `gpt-oss:120b` sur Ollama Cloud est un service hébergé, limité et susceptible de changer. Pour la reproductibilité,
  comparer avec un modèle local.
- Le connecteur Jira a été validé sur un seul site réel (Jira Cloud gratuit, un ticket). Les champs personnalisés de critères
  d'acceptation, les jetons à portée limitée et les tickets multiples n'ont été testés qu'avec des réponses simulées.
- Le workflow GitHub Actions et la publication du commentaire sont testés avec simulation, pas encore sur un dépôt réel.
- Les modèles Qwen se trompent parfois dans la liste des exigences (critère marqué « respecté » alors que le code le viole,
  vu sur nos deux exécutions Qwen) ; rien ne vérifie encore la cohérence entre la liste et les constats.
- Qwen2.5-Coder entoure son JSON de balises Markdown et a écrit une fois un nom de champ sans guillemets : l'analyseur le
  tolère et l'indique dans le rapport.

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

**Démarrage en 10 minutes** : cloner, `uv sync`, `uv run pytest -q`, définir `OLLAMA_API_KEY` (et, pour Jira, les
trois variables `JIRA_*`), ouvrir un **nouveau** terminal, puis `uv run review-agent doctor` (tout doit afficher OK),
`uv run review-agent ui --open`, et lancer une revue sur `ebirdyx/shipping-demo#1` (ticket KAN-4) ou sur votre propre PR.

Documents utiles : `docs/model-comparison-notes.md` (observations réelles par modèle), `docs/comparison-protocol.md`
(comment comparer avec Claude ou ChatGPT, sans clé d'API), `integration/code-review.yml` (workflow GitHub Actions).

À faire, dans l'ordre :

1. Lire ce fichier, puis `src/code_review_agent/schemas.py` (contrats) et `evaluation.py` (grille d'étiquetage).
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

Un cas ajouté au banc d'essai : créer `evaluation/cases/<id>/` (`ticket.json`, `pr.json`, `change.diff`) et
`evaluation/expected/<id>.json`, l'ajouter à `evaluation/split.json`, puis `uv run pytest`.
`evaluation/author_cases.py` montre comment les cas actuels ont été générés (brouillon IA : à relire).
