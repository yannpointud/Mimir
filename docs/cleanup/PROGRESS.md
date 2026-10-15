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
| 7. Dépendances | réussie | 1 | `5220999` ci: add dependabot config |
| 8. Façade | réussie | 1 | `bb8c6d8` docs: update claude guide and drop default password |

## Dernière porte franchie (passe 8)

1010 tests (1010 réussis, 0 ignoré), couverture 86,23 %, ruff 0, format OK,
radon D+ 0, mypy 0, pip-audit OK, vitest 141, build OK, `/health/live` 200 :
identique à la passe 7, la passe ne touchant que du Markdown.
README à jour (pygount : 14 600 lignes de code applicatif, 15 239 de tests),
mot de passe admin retiré du README et de CLAUDE.md, promesse d'implémentations
interchangeables remplacée par un constat, 5 ADR dans `docs/adr/`.
Voir DECISIONS D8.1 à D8.8.

Prochaine étape : FIN (revue par un sous-agent neuf, REPORT.md, suppression de PROGRESS.md, PR).

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

