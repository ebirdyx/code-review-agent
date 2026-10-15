# État du projet, évaluation et limites

[← Retour au README](../README.md)

## État du projet

| Fonction | État |
|---|---|
| Entrées locales (ticket JSON + diff) | Fait, testé |
| Contexte pour le modèle (instructions séparées du contenu non fiable, diff numéroté, budget de taille) | Fait, testé |
| Appel d'un modèle Ollama (cloud ou local) | Fait, testé (modèle réel : `gpt-oss:120b`) |
| Validation de la sortie (JSON, schéma, fichier, ligne, citations, doublons) | Fait, testé |
| Rapports JSON et Markdown | Fait, testé |
| Banc d'essai (22 cas Python, séparation dev / hold-out, précision, rappel, F1) | Fait. **Étiquettes à valider par un humain** |
| **Pipeline multi-passes** (par défaut) : 4 spécialistes (conformité au ticket critère par critère, défauts, sécurité, règles d'équipe), fusion des doublons, puis passe de **vérification** qui peut écarter un constat (toujours visible, avec la raison) | Fait, testé (tests automatiques ; exécutions réelles avec `gpt-oss:120b` et Qwen). Qualité **mesurée seulement sur peu de cas** (banc d'essai de développement et PR de démonstration, voir `evaluation/results/`) : aucun chiffre n'est définitif |
| **Analyse statique** (Ruff + Bandit, Python) : avertissements déterministes sur les lignes modifiées, fusionnés avec les constats du modèle et fournis aux passes comme pistes | Fait, testé avec les vrais outils et sur une vraie PR (pallets/click) |
| **Règles d'équipe** (`.review-agent/rules.md` lu sur la branche de base, ou `--rules`) vérifiées par une passe dédiée | Fait, testé (modèle simulé) et sur 4 exécutions réelles |
| **Profil du changement** (taille, tests modifiés ou non, zones sensibles, dépendances, CI), sans modèle | Fait, testé |
| **Contexte du dépôt** (graphe de code léger, Python) : pour chaque fonction modifiée, ses appelants, les fonctions qu'elle appelle, les tests qui la mentionnent et le constructeur de sa classe, trouvés avec `ast` dans une seule archive téléchargée | Fait, testé (simulation) et essayé sur les PR de démonstration. Effet **mesuré sur 6 + 3 PR seulement** : aucun effet quand le défaut est visible dans le diff, nette amélioration (9 trouvés sur 9 contre 2 sur 9) sur 3 PR conçues pour que le défaut soit hors du diff : voir `evaluation/results/context-ablation/` et `evaluation/results/context-dependent/` |
| **Profils de modèles** (`--profile`) : Ollama local ou cloud, Qwen2.5-Coder via un service hébergé compatible OpenAI (OpenRouter) | Fait. **Exécutions réelles** de Qwen2.5-Coder 32B et Qwen3-Coder 30B via OpenRouter sur la PR de démonstration (voir `docs/model-comparison-notes.md`). Qwen local (Ollama) **pas encore exécuté** |
| Suivi en direct (événements dans le terminal et `events.jsonl`) et interface web locale (vue d'ensemble avec indicateurs, liste des revues groupée et filtrable, vue Evaluations avec comparaison côte à côte, écran de revue en trois panneaux (constats par gravité, preuve du constat sélectionné, exigences du ticket), tri au clavier avec enregistrement automatique et annulation, rapport, chronologie, lancer une revue de PR) | Fait, testé (serveur réel en local, page vérifiée dans un vrai navigateur) |
| Lecture d'une Pull Request GitHub (lecture seule, révision exacte enregistrée) | Fait, testé avec simulation et avec l'API réelle (lecture seulement) |
| Revue d'une PR GitHub + ticket Jira liée, par le modèle | Fait et exécuté pour de vrai (PR `ebirdyx/shipping-demo#1` + `KAN-4`, `gpt-oss:120b`) : voir `evaluation/results/real-pr-demo/` |
| Tickets Jira (lecture seule, lien PR → ticket, critères d'acceptation, tickets multiples ou indisponibles) | Fait. Testé avec simulation **et sur un vrai site Jira Cloud** (`fetch-ticket KAN-4` : critères lus dans la section de la description). Le cas « champ personnalisé » n'a été testé qu'avec simulation |
| Commentaire unique et auto-mis à jour sur la PR (`--post-comment`) et modèle de workflow GitHub Actions (`integration/code-review.yml`) | Fait et testé (simulation). **Pas encore actif sur un vrai dépôt** : voir `usage.md`, section « Intégration GitHub Actions » |
| Comparaison avec Claude / ChatGPT / Gemini | Outillage prêt (`eval-export`, `eval-import`, `eval-compare`, protocole dans `docs/comparison-protocol.md`). **Résultats à produire** par l'équipe, dans des fenêtres de chat neuves |
| Banc d'essai sur un modèle local libre (Qwen2.5-Coder, etc.) | **À faire** (l'outil le permet déjà) |

## Méthode d'évaluation

- **Cas** : `evaluation/cases/` (19 cas Python) et `examples/` (3 cas), répartis en boundary, logic, requirement,
  error_handling, security, correct, plus un cas d'injection de prompt dans le ticket.
- **Réponses attendues** : `evaluation/expected/`, écrites à la main, **jamais dans les prompts** (un test le vérifie).
  Chaque défaut attendu a une ligne calculée à partir d'un extrait de code (`code_anchor`), vérifiée par test.
- **Séparation** : `evaluation/split.json`. *dev* (9 cas) sert à améliorer le prompt ; *heldout* (13 cas) ne se lance
  qu'une fois le prompt figé (`--confirm-frozen`).
- **Étiquettes** (grille écrite avant les résultats, voir `evaluation/scoring.py`) : `tp`, `fp`, `duplicate` (compté une fois), `extra`
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
- Le contexte du dépôt : aucun effet sur les 6 PR de démonstration (défauts visibles dans le diff) ; sur 3 PR **que nous avons conçues** pour que le défaut soit hors du diff,
  9 défauts trouvés sur 9 avec contexte contre 2 sur 9 sans (3 exécutions chacune, un seul modèle, lecture non à l'aveugle). Cela montre que la fonction sert quand elle est nécessaire,
  pas à quelle fréquence de vraies PR en ont besoin. Elle ajoute environ 14 % de jetons en entrée ; appels trouvés par nom (peuvent désigner la mauvaise fonction) ; Python seulement.
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
