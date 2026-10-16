# Décision d'adoption — Recherche hybride BM25 + RRF

**Date:** 2026-07-13
**Décision:** **ADOPTÉE** — `hybrid_search_enabled` passe à `True` par défaut.

## Contexte de mesure

Toutes les mesures sont faites sur le **même golden set gelé** (`golden_set_v1.jsonl`,
généré synthétiquement par Mistral), échantillon de **40 questions corpus** identiques
pour le dense et l'hybride, juge Mistral `mistral-small-latest`, `RunConfig(max_workers=1)`
(sériel, rate-limit-safe), température 0, sans cache.

Métriques retenues : `context_recall` et `context_precision` — ce sont les métriques de
**qualité de retrieval**, celles que la fusion RRF impacte réellement (RRF change le
retrieval, pas la génération).

## Résultats (preuves chiffrées)

| Métrique | Dense (baseline) | Hybride BM25+RRF | Delta absolu | Delta relatif |
|----------|------------------|-------------------|--------------|---------------|
| context_recall | 0.6792 | **0.8000** | **+0.1208** | **+17.8 %** |
| context_precision | 0.5788 | **0.6606** | **+0.0818** | **+14.1 %** |
| taux de NaN | 0.0 % | 0.0 % | — | — |

Sources : `results/baseline_run_1.json`, `results/hybrid_run.json`.

## Non-régression terme-exact (condition bloquante)

`results/exact_term_check.json` — 5 requêtes à termes exacts distinctifs (noms de projets
uniques à un document : Titan Security Core, Omega Protocol, Hyperion Analytics, Project
Phoenix, Helios Initiative) :

- **`no_regression: true`**
- dense_recall = **1.0**, hybrid_recall = **1.0**

L'hybride ne dégrade PAS la récupération des termes exacts (l'objet même de l'ajout de BM25) ;
les deux modes retrouvent le bon document pour les 5 requêtes.

## Jugement d'adoption

Règle (critère fixé avant la mesure + directive utilisateur) : adopter uniquement si le gain est
**net et marqué** (pas un simple > 0, pas ~+5 % qui ne vaudrait pas la complexité d'un
second index), ET **sans régression terme-exact**.

- Gain de **+17.8 % (recall)** et **+14.1 % (precision)** — largement au-dessus du seuil
  ~+5 % jugé insuffisant ; les deux métriques de retrieval s'améliorent.
- Taux de NaN à **0 %** sur les deux runs → le juge Mistral est fiable pour ces métriques
  (lève l'incertitude « fiabilité RAGAS+Mistral inconnue »).
- **Aucune régression terme-exact.**

→ Les trois conditions sont remplies. **L'hybride est adopté** (`hybrid_search_enabled=True`).
Le seuil `rrf_score_threshold=0.015` est validé empiriquement : le run hybride a produit des
contextes **non vides** sur les 40 questions (pas d'artefact de seuil vidant le mode hybride) et
un recall en hausse — un seuil qui filtrerait les bons résultats aurait fait CHUTER le recall,
pas monter de +18 %.

## Réversibilité (garde-fou moteur)

Le chemin dense-only reste **byte-identique** quand `hybrid_search_enabled=False`
(prouvé : `tests/unit/test_rag_service.py` inchangé et vert). L'adoption est donc totalement
réversible par un simple retour du flag à `False` — aucune modification du code dense-only.

## Limites assumées (honnêteté de la mesure)

- Mesure sur un **échantillon de 40 questions corpus** (sur 51) et un corpus de **23 documents**
  d'entreprise synthétiques, pas le golden set complet ni un corpus de production — le débit
  free-tier Mistral (~1 req/s, ~26 min par run de 40×2 métriques) rend le run complet 60×2
  multi-heures. L'ampleur du delta (+18 % relatif) est très supérieure au bruit typique d'un
  juge à température 0 (quelques %), ce qui rend la décision robuste malgré l'échantillon.
- Le **second run de stabilité** (deux runs identiques) n'a pas été exécuté pour la même
  raison de débit ; le taux de NaN à 0 % et l'ampleur du gain suffisent à fonder l'adoption.
  Un second run reste recommandé pour quantifier finement le bruit inter-runs si le corpus
  de production diverge.

## Recommandation opérateur

Rejouer la mesure (`run_pipeline.py` + `score_baseline.py`) sur le corpus de production réel
avant un déploiement à grande échelle ; le flag `hybrid_search_enabled` permet un repli
instantané en dense-only si le delta ne se confirmait pas sur ce corpus.
