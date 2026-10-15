# Avancement de la mission

Consigne : `docs/cleanup/MISSION.md`. Décisions : `docs/cleanup/DECISIONS.md`.

| Passe | État | Tentatives | Dernier commit poussé |
| --- | --- | --- | --- |
| 0. Oracle | réussie | 1 | `8abe5a3` docs(cleanup): track progress after pass 0 |
| 1. Lint | réussie | 1 | `7501847` docs(cleanup): record pass 1 decisions and progress |
| 2. Erreurs | réussie | 1 | `c5362df` docs(cleanup): record pass 2 decisions and progress |
| 3. Architecture | réussie | 1 | `f810329` docs(cleanup): record pass 3 decisions and progress |
| 4. Typage | réussie | 1 | `94e6946` docs(cleanup): record pass 4 decisions and progress |
| 5. Commentaires | réussie | 1 | `7dee121` docs: remove planning references from comments and strings |
| 6. Tests | réussie | 1 | `feea00c` test: kill surviving mutants in chunking and fusion |
| 7. Dépendances | en cours | 1 | |
| 8. Façade | à faire | 0 | |

## Dernière porte franchie (passe 6)

1010 tests (1010 réussis, 0 ignoré), couverture 86,23 %, ruff 0, format OK,
radon D+ 0, mypy 0, pip-audit OK, vitest 141, build OK, `/health/live` 200.
62 tests supprimés (29 ne vérifiaient que des mocks ou rien, 33 doublons),
27 ajoutés ; mutmut : `fusion` 17/17 et `tokenizer_fr` 15/15 tués, `chunking`
364/403 (39 survivants non significatifs). Voir DECISIONS D6.1 à D6.6.

Prochaine étape : passe 7 (dépendances), en cours (tentative 1).

## Reprendre après une coupure

1. Relire `MISSION.md`, ce fichier, puis `sha256sum -c docs/cleanup/ORACLE.sha256`
   (l'oracle existe : ne jamais refaire la passe 0).
2. Environnement : `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   -r requirements-dev.txt`, puis `cd frontend && npm ci`.
3. Variables factices pour pytest : `MISTRAL_API_KEY=test-key`, `JWT_SECRET_KEY` de
   32 caractères aléatoires, `ENVIRONMENT=test`, `unset MISTRAL_MODEL` (ne jamais les
   afficher). La porte les force elle-même.
4. Porte de qualité : `bash docs/cleanup/quality_gate.sh <dossier>` puis comparer
   `<dossier>/metrics.env` aux métriques de la dernière porte ci-dessus.
5. Reprendre la première passe qui n'est pas « réussie » ou « annulée », depuis le
   dernier commit poussé ; les tentatives déjà notées comptent (3 maximum).

