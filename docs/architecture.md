# Architecture et fonctionnement

[← Retour au README](../README.md)

## Architecture et responsabilités

Le code (`src/code_review_agent/`) est organisé en couches. Chaque dossier a **une seule responsabilité** et les dépendances vont toujours dans le même
sens : `app` utilise tout ; `evaluation` utilise `connectors` et `pipeline` ; `pipeline` utilise `context` et `llm` ; `connectors` utilise `context` ;
`llm`, `context` et `reporting` n'utilisent que les contrats partagés (`schemas.py`). Aucune dépendance circulaire (vérifié sur les vrais imports).

```
ticket Jira / PR GitHub / dossier local
        |
  connectors/    lire les entrées (lecture seule) -> instantané enregistré sur disque
        |
  context/       préparer ce que le modèle verra : contexte, graphe de code, analyse statique
        |
  pipeline/      passes spécialisées -> fusion -> vérificateur -> validation -> résultat    <--  llm/ (clients et profils de modèles)
        |
  reporting/     rapport Markdown, commentaire de PR

  app/           ligne de commande, service partagé, interface web locale
  evaluation/    mesurer l'agent : notation et comparaison de configurations
```

| Dossier | Fichier | Rôle |
|---|---|---|
| (racine) | `schemas.py` | Contrats de données (Pydantic) : ticket, entrée, constat, résultat. |
| | `events.py` | Événements de progression (terminal, `events.jsonl`, interface web). |
| `connectors/` | `github.py` | Lecture seule d'une PR : pagination, patchs absents, PR trop grande, vérification que la PR n'a pas changé pendant la lecture, téléchargement du dépôt en une archive. |
| | `jira.py` | Lecture seule d'un ticket Jira : critères d'acceptation, lien PR vers ticket, erreurs expliquées. |
| | `snapshot.py` | Lit et écrit les dossiers d'exemple et les instantanés de PR (rejouables hors ligne). |
| `context/` | `builder.py` | Construit le contexte. Les instructions (`prompts/`) sont séparées du contenu non fiable, encadré de marqueurs. Le diff reçoit des numéros de ligne. Ce qui manque ou ne tient pas dans le budget est **signalé**, jamais tronqué en silence. |
| | `codegraph.py` | Graphe de code léger (`ast`) : appelants, fonctions appelées, tests et classe des fonctions modifiées. |
| | `evidence.py` | Analyse statique (Ruff, Bandit) en bac à sable, correspondance avec les lignes modifiées, profil du changement. |
| `llm/` | `client.py` | Deux clients derrière la même interface : Ollama et API compatible OpenAI (via LangChain). Erreurs classées (connexion, délai, clé, quota, crédit, modèle introuvable). |
| | `profiles.py`, `models.toml` | Profils de modèles nommés et documentés (aucun secret). |
| `pipeline/` | `multi.py` | Exécution du pipeline multi-passes : analyse statique, appels aux spécialistes (en parallèle), vérificateur. |
| | `single.py` | Pipeline à un seul appel (la référence de comparaison, `--pipeline single`). |
| | `records.py` | Ce qu'une exécution a enregistré (contexte envoyé, réponses brutes, réglages, révision revue) et son enregistrement dans `run.json`. |
| | `passes.py` | Les passes qui existent, le schéma JSON de chacune, les prompts (`prompts/multi_vN/`). |
| | `blocks.py` | Ce que le modèle voit en plus du ticket et du diff : pistes d'analyse statique, règles d'équipe, code lié, message du vérificateur. |
| | `merge.py` | Fusion des signalements d'un même problème en un seul constat (sans perdre ni preuve ni explication). |
| | `consistency.py` | Contrôle de cohérence : un critère « respecté » alors qu'un constat dit que le code cité est faux est signalé (jamais corrigé). |
| | `assemble.py` | Fonction **pure** : transforme une exécution enregistrée en `ReviewResult` et reconstruit le texte exact envoyé (`context.txt`). Aucun appel au modèle. |
| | `validation.py` | Rejette un JSON invalide ou hors schéma. Vérifie que fichier, ligne et citations existent dans l'entrée. **Ne corrige jamais une localisation** : elle est signalée. |
| | `textutil.py` | Petit utilitaire de texte partagé. |
| `reporting/` | `report.py` | Rapport Markdown. Un échec de revue n'est jamais présenté comme « aucun constat ». |
| | `comment.py` | Commentaire unique de PR, avec le texte du modèle neutralisé (mentions, HTML, liens). |
| `evaluation/` | `scoring.py` | Étiquetage humain, précision, rappel, F1, exactitude de la ligne et de la catégorie. |
| | `comparison.py` | Évaluation reproductible : configuration enregistrée par `eval-run`, comparaison côte à côte par `eval-compare`. |
| `app/` | `cli.py` | Les commandes `review-agent` (aussi `python -m code_review_agent`). |
| | `service.py` | Le flux de travail partagé par la ligne de commande et l'interface web. |
| | `ui.py`, `web/` | Interface web locale. |

### Pipeline multi-passes

Un petit modèle réussit mieux une tâche étroite que « tout relire ». Chaque revue lance donc des spécialistes avec le même contenu mais des consignes différentes :

| Passe | Rôle | Sortie |
|---|---|---|
| `compliance` | Compare le code à **chaque critère d'acceptation** du ticket (ignorée sans ticket ni critères) | Un verdict par critère : *met*, *not met* ou *cannot determine*, avec preuves citées |
| `standards` | Compare les lignes ajoutées aux **règles d'équipe** (ignorée sans fichier de règles) | Constats citant la règle et le code |
| `defects` | Erreurs de logique, cas limites, gestion d'erreurs, maintenabilité | Constats |
| `security` | Vulnérabilités concrètes introduites par le changement | Constats |
| `verify` | Deuxième regard indépendant sur chaque constat candidat | *supported*, *uncertain* ou *unsupported* (écarté, mais **affiché** avec la raison) |

La fusion regroupe les signalements d'un même problème (même fichier et même ligne ; si les catégories diffèrent, il faut en plus qu'ils citent le même code, emploient en grande partie les mêmes mots, ou que l'un vienne d'un outil d'analyse statique) en gardant la catégorie la plus précise, la gravité la plus haute et toutes les preuves ; deux remarques sans rapport qui tombent sur la même ligne restent séparées.
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
modifiée, `context/codegraph.py` retrouve (avec le module standard `ast`, sans base vectorielle) : les fonctions qui l'appellent, celles qu'elle appelle,
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
