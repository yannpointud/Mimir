# Avancement de la mission

Consigne : `docs/cleanup/MISSION.md`. Décisions : `docs/cleanup/DECISIONS.md`.

| Passe | État | Tentatives | Dernier commit poussé |
| --- | --- | --- | --- |
| 0. Oracle | réussie | 1 | `8abe5a3` docs(cleanup): track progress after pass 0 |
| 1. Lint | réussie | 1 | `7501847` docs(cleanup): record pass 1 decisions and progress |
| 2. Erreurs | réussie | 1 | `c5362df` docs(cleanup): record pass 2 decisions and progress |
| 3. Architecture | réussie | 1 | `4a15285` refactor(app): split lifespan startup and shutdown steps |
| 4. Typage | à faire | 0 | |
| 5. Commentaires | à faire | 0 | |
| 6. Tests | à faire | 0 | |
| 7. Dépendances | à faire | 0 | |
| 8. Façade | à faire | 0 | |

## Dernière porte franchie (passe 3)

1045 tests (1042 réussis, 3 ignorés), couverture 85,88 %, ruff 0, format OK,
radon D+ 0, mypy 112, pip-audit OK, vitest 141, build OK, `/health/live` 200.
Plus aucun `noqa: C901` ; les 7 handlers de plus de 100 lignes en font
désormais moins de 60 (logique déplacée dans `backend/src/services/`).

Prochaine étape : passe 4 (typage).
