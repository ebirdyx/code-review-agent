# Configuration du modèle, des profils et des services

[← Retour au README](../README.md)

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

## Versions utilisées

Voir aussi `uv.lock` : Python 3.12.10, pydantic 2.13.5, langchain-ollama 1.1.0, httpx 0.28.1.

## Licences

| Élément | Licence |
|---|---|
| Ce logiciel | MIT (voir `LICENSE`) — à confirmer par l'équipe |
| `gpt-oss` (poids ouverts) | Apache-2.0 (vérifié sur les pages Hugging Face et Ollama) |
| Qwen2.5-Coder 14B / 32B | Apache-2.0 (vérifié sur les pages Hugging Face) |
| Rapport d'équipe | À décider |

Ollama Cloud est un **service** : l'utiliser a des limites d'usage (palier gratuit), et le code envoyé quitte la machine.
N'y envoyez pas de code confidentiel.
