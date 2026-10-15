Mission : nettoyer le dépôt Mimir de bout en bout, en autonomie complète. Objectif : un code propre et présentable, sans aucun changement de comportement. Personne ne relira le code : la seule validation est la porte de qualité ci-dessous. Ne pose aucune question. Face à un choix, prends l'option la plus conservatrice et note-la dans docs/cleanup/DECISIONS.md.

DÉJÀ FAIT (ne pas refaire)
- PR #1 (mergée) : dépendances vulnérables montées (pip-audit vert, 2 avis ignorés et justifiés : orjson bloqué par mistralai 0.4.2, pytest 7), jinja2 déclaré, bug du test BM25 corrigé, CI GitHub Actions (pytest + pip-audit sur chaque PR), références à des documents de planning retirées des commentaires.
- PR #2 : passage à Python 3.13. Prérequis : elle est mergée dans main. Sinon, note-le dans DECISIONS.md et garde la version de Python de main.
- Ordres de grandeur mesurés avant cette mission (à confirmer en passe 0) : 1013 tests (1010 réussis, 3 ignorés), couverture 82,9 %, vitest 141 tests, ruff 4 erreurs F401, radon 5 fonctions notées D ou pire, mypy 126 erreurs dans 22 fichiers, 181 except Exception dans backend/src, 7 handlers de plus de 100 lignes, 17 endpoints en response_model=Dict.

ENVIRONNEMENT
- python3 est en 3.13. Crée le venv du projet avec python3 -m venv .venv, puis installe requirements.txt et requirements-dev.txt.
- L'environnement exporte une vraie MISTRAL_API_KEY et un MISTRAL_MODEL. Pour les tests, la CI et la porte de qualité, force des valeurs factices : MISTRAL_API_KEY=test-key, JWT_SECRET_KEY aléatoire de 32 caractères, ENVIRONMENT=test, et unset MISTRAL_MODEL. N'affiche jamais ces variables. Aucune clé réelle dans le code ni dans les commits.

STYLE
- Commits : une ligne, courte, style conventionnel, sans corps (sauf un revert : une phrase de raison). Exemples : "lint: enable ruff B, SIM, UP", "refactor(chat): split rag stream steps".
- Pull request finale : titre court.

RÈGLES
- Pars de main à jour. Pose le tag pre-cleanup sur main et pousse-le.
- Travaille sur la branche cleanup/qualite. Ne pousse jamais sur main, ne réécris jamais l'historique (ni force-push, ni amend d'un commit poussé).
- Pousse chaque passe dès qu'elle est verte. Mets à jour docs/cleanup/PROGRESS.md à la fin de chaque passe (passe, état, dernier commit, prochaine étape). Au démarrage, si PROGRESS.md existe déjà sur la branche, reprends là où il s'arrête.
- Aucun changement fonctionnel : mêmes routes, mêmes codes HTTP, mêmes JSON, mêmes messages renvoyés au client. Une seule correction autorisée : le log perdu dans IngestionProcessor.queue_document (un Path non sérialisable en JSON), en passe 2.
- Garde le 403 de JWTBearer (surcharge de make_not_authenticated_error) : FastAPI >= 0.122 renverrait 401, et le frontend déconnecte l'utilisateur sur tout 401.
- Ne migre pas le SDK Mistral.

PASSE 0 : L'ORACLE (avant toute modification)
1. Ajoute radon, mypy, pygount et mutmut à requirements-dev.txt. Mesure l'état initial et écris-le dans docs/cleanup/BASELINE.md : pytest (total, échecs, couverture), vitest et build du front (npm ci, npx vitest run, npm run build), ruff (config actuelle, puis --select B,SIM,UP,BLE,C90), radon (cc -n D), mypy (backend/src, mode normal), pip-audit (avec les deux exclusions de la CI).
2. Écris des tests de caractérisation dans tests/oracle/ :
   a. un snapshot du schéma OpenAPI limité aux chemins, méthodes, paramètres, corps de requête et codes de statut. Les schémas de réponse en sont exclus : la passe 4 va les typer ;
   b. les réponses JSON des principaux endpoints (documents, admin, health, auth), valeurs volatiles neutralisées. C'est ce test qui garantit que le JSON ne change pas ;
   c. pour 10 questions fixes sur un corpus de test fixe, avec un LLM et des embeddings factices déterministes : la séquence des événements SSE de /chat/stream, en neutralisant horodatages, durées et identifiants (inspire-toi de tests/integration/test_chat_stream_cache.py) ;
   d. pour ces mêmes questions, les ids et l'ordre des résultats en recherche dense et en recherche hybride ;
   e. l'ingestion d'un PDF, d'un DOCX, d'un TXT et d'un MD : nombre et texte des chunks.
3. Écris dans docs/cleanup/ORACLE.sha256 la somme SHA256 de chaque fichier source (hors __pycache__) de tests/oracle/ et de tests/integration/. Ces fichiers sont gelés : tu ne les modifies plus jamais. Si un test gelé dépend d'un détail interne (un import, ou un handler appelé directement avec ses arguments, comme rebuild_vector_store), conserve ce point d'entrée (réexport, même signature) plutôt que de toucher au test.

PORTE DE QUALITÉ (à franchir à la fin de chaque passe)
- sha256sum -c docs/cleanup/ORACLE.sha256 réussit ;
- tous les tests de tests/oracle et tests/integration passent ;
- le nombre total de tests ne baisse pas de plus de 5 %, la couverture pas de plus d'un point ;
- vitest et le build du front passent ;
- dans un venv vierge, une installation depuis requirements.txt réussit, uvicorn démarre et GET /api/v1/health/live renvoie 200 ;
- aucune nouvelle alerte ruff, mypy ni pip-audit par rapport à la passe précédente. Un avis pip-audit publié pendant la mission et sans lien avec la passe ne la bloque pas : note-le dans DECISIONS.md.
Si une passe échoue après 3 tentatives, annule-la avec git revert, explique pourquoi dans DECISIONS.md et passe à la suivante.

PASSES
1. Lint. Exclus tests/oracle et tests/integration de ruff format et de tout autofix, sinon les sommes SHA256 cassent. Corrige les 4 F401 existants. Active B, SIM, UP, BLE et C90 (max-complexity 15) dans pyproject.toml, en ignorant B008 (Depends de FastAPI). Applique les autofix sûrs dans un commit, puis ruff format dans un commit séparé. Ce qui ne se corrige pas dans cette passe (C901, BLE001) est mis en baseline par des noqa ciblés avec le code de la règle ; les passes 2 et 3 les retireront. Ajoute ruff check et ruff format --check à la CI, en bloquant.
2. Erreurs. Ne garde except Exception qu'aux frontières (endpoints, worker d'ingestion, stream SSE), avec log et un noqa BLE001 justifié. Ailleurs, utilise des exceptions précises ou métier (IngestionError, RetrievalError, LLMError, BudgetExceeded), traduites en HTTP par des handlers FastAPI. Ajoute raise ... from e là où il manque. Les codes HTTP et les messages renvoyés au client ne changent pas : l'oracle 0.2.b fait foi.
3. Architecture. Découpe _process_question_with_rag_stream en étapes nommées. Ramène sous 60 lignes les handlers qui en font plus de 100 (chat_stream, upload_document, admin_upload_document, delete_document, rebuild_vector_store, get_document_with_chunks, validate_vector_store_consistency) en déplaçant leur logique dans des services. Fusionne la logique commune des deux endpoints d'upload. Type RagService et les dépendances sur les interfaces de rag_core et llm_interface (le store BM25 n'implémente pas AbstractVectorStore : donne-lui un Protocol). Cible : plus aucune fonction notée D ou pire par radon, plus aucun noqa C901. En dehors de ces cibles, ne touche pas aux fonctions déjà notées A, B ou C.
4. Typage. mypy en mode normal sur backend/src, zéro erreur, ajouté à la CI en bloquant. ignore_missing_imports seulement par module, pour les bibliothèques sans stubs (faiss, bm25s...). Remplace les Dict[str, Any] renvoyés par les services et les principaux endpoints par des modèles Pydantic, sans changer le JSON produit : l'oracle 0.2.b fait foi.
5. Commentaires. Supprime les docstrings qui ne font que répéter la signature. Garde celles des API publiques et les commentaires qui expliquent un pourquoi. Il ne reste des références à des documents de planning que dans des chaînes : descriptions Field de config.py (non exposées dans l'API), aide argparse et print des scripts de scripts/ragas_eval, un message d'assertion, un describe vitest, et les documents scripts/ragas_eval/*.md. Nettoie-les toutes, sauf les libellés de contrôles de scripts/validate_milestone.sh, définis par le script lui-même.
6. Tests. Hors tests/oracle et tests/integration, supprime les tests qui ne vérifient que des mocks ou qui font doublon, en justifiant chaque suppression dans DECISIONS.md. Lance mutmut sur rag_core/fusion, ingestion/chunking et rag_core/tokenizer_fr, et ajoute des tests pour tuer les mutants survivants significatifs. Ajoute mutants/ au .gitignore.
7. Dépendances. Le projet n'est pas un paquet Python : génère des lockfiles avec uv pip compile --generate-hashes (requirements.lock et requirements-dev.lock) et utilise-les dans la CI ; requirements.txt reste la source. Ajoute une configuration Dependabot pour pip, npm (frontend/) et github-actions. Déplace aiosqlite dans la section runtime de requirements.txt (il sert à l'exécution). Si pytest 9 et un pytest-asyncio récent passent la porte sans toucher aux tests gelés, monte-les et retire l'exclusion pip-audit de pytest ; sinon, revert et note-le. Ne migre pas le SDK Mistral : sans test contre la vraie API, des tests simulés ne prouvent rien sur ce point, et l'exclusion orjson reste.
8. Façade. Mets à jour le README. Donne des chiffres mesurés avec pygount, en séparant code applicatif et tests. Retire le mot de passe admin par défaut du README et de CLAUDE.md. Retire de CLAUDE.md la promesse d'implémentations interchangeables si elle reste fausse. Écris 4 ou 5 ADR dans docs/adr/ pour les vraies décisions : budget IA par réservation, recherche hybride BM25 avec RRF, évaluation RAGAS, SQLite WAL avec FAISS local, streaming SSE.

FIN
1. Lance un sous-agent neuf, sans contexte sur ce travail. Sa seule consigne : relire le diff complet entre pre-cleanup et la branche, y chercher les changements de comportement, les régressions de sécurité, le code mort laissé et les tests affaiblis, puis produire un rapport. Corrige chaque point qu'il juge bloquant, puis repasse la porte de qualité.
2. Optionnel : un test réel avec la clé de l'environnement (ingestion de 3 documents, 2 questions en streaming, un rebuild admin), sans jamais l'afficher ni l'écrire.
3. Écris docs/cleanup/REPORT.md : un tableau avant/après (tests, couverture, ruff, radon, mypy, pip-audit), la liste des passes réussies ou annulées, et les décisions prises. Supprime PROGRESS.md dans le dernier commit.
4. Ouvre une seule pull request vers main, titre court, avec ce rapport en description. Ne la merge pas.

REPRISE
- Avant toute chose, copie cette consigne mot pour mot dans docs/cleanup/MISSION.md, puis commit et pousse.
- Dans PROGRESS.md, note pour chaque passe : son état (à faire, en cours, réussie, annulée), le nombre de tentatives et le dernier commit poussé.
- Pour économiser le contexte, confie chaque passe à un sous-agent, avec MISSION.md comme consigne. Ne garde dans la conversation principale que son compte rendu et le résultat de la porte de qualité.
- Après une compaction ou dans une nouvelle session : relis MISSION.md et PROGRESS.md, puis vérifie ORACLE.sha256. Si l'oracle existe, ne refais jamais la passe 0. S'il faut la refaire, pars du tag pre-cleanup. Reprends à la première passe non terminée, depuis le dernier commit poussé. Les tentatives déjà faites comptent dans la limite de 3.
