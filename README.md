# Mimir - Chatbot Documentaire d'Entreprise

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-green.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-teal.svg)
![React](https://img.shields.io/badge/React-18.2-blue.svg)
![License](https://img.shields.io/badge/license-Proprietary-red.svg)

Mimir est une solution de chatbot intelligent RAG (Retrieval Augmented Generation) destinée aux entreprises, permettant aux employés d'obtenir des réponses instantanées et fiables basées exclusivement sur la documentation interne. La solution garantit la confidentialité totale des données en fonctionnant entièrement sur l'infrastructure du client.

## 🎬 Démonstration

![Démonstration Mimir](DemoMimir.mp4)

## 🎯 Vision et Objectifs

### Objectifs Métiers
- **Productivité** : Réduire de 70% le temps de recherche d'information
- **Fiabilité** : 100% des réponses basées sur documentation officielle
- **Intégration** : Accélération de l'onboarding des nouveaux employés
- **Confidentialité** : Aucune donnée ne quitte l'infrastructure client
- **Simplicité** : Déploiement en moins de 30 minutes

### Indicateurs de Succès
- Temps moyen de réponse < 3 secondes
- Taux de satisfaction utilisateur > 85%
- Réduction des tickets support documentation de 50%
- 0 fuite de données

## ✨ Fonctionnalités

### Module Chat
- Interface web de conversation en langage naturel
- Historique de session temps réel
- Citation des sources pour chaque réponse
- Indicateur visuel pendant la génération
- Bouton d'escalade vers opérateur humain
- Score de confiance affiché pour chaque réponse

### Module Administration
- Authentification sécurisée (JWT)
- Upload manuel de documents (PDF, DOCX, TXT, MD)
- Surveillance automatique de dossier partagé
- Liste et gestion des documents indexés
- **Nettoyage automatique des chunks orphelins** (rebuild index)
- Configuration email d'escalade
- Indicateurs de santé système en temps réel
- Tableau de bord avec métriques d'utilisation

### Module Ingestion
- Extraction de texte multi-format
- Chunking intelligent avec overlap
- Génération d'embeddings (Mistral API)
- Indexation vectorielle (FAISS)
- Queue séquentielle anti-saturation
- Protection documents critiques
- Traitement asynchrone avec retry logic
- **Nettoyage automatique des chunks orphelins**

### Module RAG
- Recherche sémantique par similarité
- Scoring multi-critères (pertinence + fraîcheur + boost nom de fichier)
- Contexte limité à la documentation
- Pas d'hallucination (réponse "je ne sais pas" si incertitude)
- Filtrage dynamique des sources
- Cache intelligent des réponses

## 🏗️ Architecture

![Architecture Mimir](Architecture.png)

### Stack Technologique

#### Backend
- **Framework** : Python 3.11+, FastAPI, Uvicorn
- **Base de données** : SQLite (mode WAL)
- **Index vectoriel** : FAISS (local)
- **LLM** : Mistral API (mistral-small-latest)
- **Cache** : LRU cache thread-safe avec TTL
- **Email** : aiosmtplib pour escalades
- **Auth** : JWT avec bcrypt

#### Frontend
- **Framework** : React 18 avec hooks
- **Build** : Vite
- **UI** : Tailwind CSS
- **HTTP** : Axios avec intercepteurs
- **Routing** : React Router v6

#### Infrastructure
- **Logs** : Système centralisé JSON structuré

### Architecture Modulaire

```
backend/
├── main.py                    # Point d'entrée FastAPI
├── src/
│   ├── api/
│   │   ├── endpoints/         # Routes REST (chat, documents, admin, auth, health)
│   │   ├── middleware/        # CORS, rate limiting
│   │   └── dependencies.py    # Injection de dépendances
│   ├── auth/                  # JWT, password utils, middleware
│   ├── cache/                 # LRU cache services
│   ├── config.py              # Configuration Pydantic centralisée
│   ├── database/
│   │   ├── models.py          # Modèles ORM SQLAlchemy
│   │   ├── repository.py      # Pattern Repository
│   │   └── connection.py      # Gestion connexions DB
│   ├── email_service/         # Service SMTP pour escalades
│   ├── ingestion/
│   │   ├── processor.py       # Pipeline d'ingestion
│   │   ├── extractors.py      # Extraction multi-format
│   │   ├── chunking.py        # Stratégie de découpage
│   │   └── async_queue_manager.py  # Queue asynchrone
│   ├── llm_interface/
│   │   ├── interfaces.py      # Abstractions LLM
│   │   └── implementations/mistral_api.py
│   ├── rag_core/
│   │   ├── interfaces.py      # Abstractions Vector Store
│   │   └── implementations/faiss_store.py
│   ├── monitoring/            # Logging centralisé JSON
│   ├── shared/                # Modèles Pydantic partagés
│   └── utils/                 # Utilitaires (logs reader, parser)
└── tests/
    ├── unit/                  # Tests unitaires
    ├── integration/           # Tests d'intégration
    └── e2e/                   # Tests end-to-end

frontend/
├── src/
│   ├── components/
│   │   ├── Chat/              # Interface de conversation
│   │   ├── Admin/             # Tableau de bord admin
│   │   └── Common/            # Composants réutilisables
│   ├── services/
│   │   └── api.js             # Client API centralisé
│   ├── hooks/                 # Hooks personnalisés (useAuth)
│   └── utils/                 # Utilitaires (storage, logger, auth)
└── package.json
```

## 🚀 Installation et Déploiement

### Prérequis
- Python 3.11+
- Node.js 18+
- Clé API Mistral
- Minimum 16GB RAM

### Installation locale

#### 1. Backend

```bash
cd backend

# Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou venv\Scripts\activate  # Windows

# Installer les dépendances
pip install -r requirements.txt

# Créer le fichier .env
cp .env.example .env
# Éditer .env et configurer MISTRAL_API_KEY

# Initialiser la base de données
python scripts/init_db.py

# Lancer le serveur
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

#### 2. Frontend

```bash
cd frontend

# Installer les dépendances
npm install

# Lancer le serveur de développement
npm run dev
```

L'application sera accessible sur :
- Frontend : http://localhost:5173
- Backend API : http://localhost:8000
- Documentation API : http://localhost:8000/docs

## ⚙️ Configuration

### Variables d'environnement principales

```bash
# API Configuration
API_VERSION=v1
API_HOST=0.0.0.0
API_PORT=8000

# Database
DATABASE_URL=sqlite:///./data/sqlite/mimir.db
SQLITE_WAL_MODE=true

# LLM Configuration
MISTRAL_API_KEY=votre_clé_api_mistral
MISTRAL_MODEL=mistral-small-latest
MISTRAL_EMBEDDING_MODEL=mistral-embed
EMBEDDING_DIMENSION=1024

# Vector Store
FAISS_INDEX_PATH=./data/faiss/index.bin
FAISS_METADATA_PATH=./data/faiss/metadata.pkl
SIMILARITY_THRESHOLD=0.5
MAX_SOURCES=5

# Cache
CACHE_ENABLED=true
CACHE_MAX_SIZE=1000
CACHE_TTL=3600

# Email (pour escalades)
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=notification@example.com
SMTP_PASSWORD=votre_password
ESCALATION_EMAIL=support@example.com

# Security
JWT_SECRET_KEY=votre_secret_très_long_et_sécurisé
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440
ADMIN_PASSWORD_HASH=bcrypt_hash_du_password

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60

# Logging
LOG_LEVEL=INFO
```

### Génération du hash admin

```bash
cd backend
python -c "from src.auth.jwt_handler import JWTHandler; print(JWTHandler().hash_password('votre_password'))"
```

## 📚 Utilisation

### 1. Connexion Admin

Accédez à l'interface admin et connectez-vous avec :
- Username : `admin`
- Password par défaut : `Abc1234`

Le mot de passe peut être modifié depuis l'interface Admin > Configuration.

### 2. Upload de Documents

Deux méthodes :

**Upload manuel :**
- Naviguez vers "Documents" dans l'admin
- Cliquez sur "Upload Document"
- Sélectionnez vos fichiers (PDF, DOCX, TXT, MD)

**Surveillance automatique :**
- Placez vos documents dans `./backend/data/uploads/`
- Le système détectera et indexera automatiquement

### 3. Chat avec le Bot

- Accédez à l'interface de chat
- Posez vos questions en langage naturel
- Consultez les sources citées pour chaque réponse
- Utilisez le bouton d'escalade si nécessaire

### 4. Monitoring

- Tableau de bord admin pour métriques en temps réel
- Health check : `/api/v1/health`
- Logs système : `/backend/logs/`

## 🧪 Tests

### Tests Unitaires

```bash
cd backend

# Lancer tous les tests unitaires
python -m pytest tests/unit/ -v

# Avec couverture
python -m pytest tests/unit/ --cov=backend/src --cov-report=html
```

### Tests d'Intégration

```bash
# Tests d'intégration complète
python -m pytest tests/integration/ -v
```

### Couverture de Tests

La suite de tests couvre les modules principaux : auth, cache, database, API endpoints, ingestion et RAG core.

## 🛠️ API Documentation

L'API REST complète est documentée via OpenAPI/Swagger :

**Accès à la documentation :**
- Swagger UI : http://localhost:8000/docs
- ReDoc : http://localhost:8000/redoc

### Endpoints principaux

#### Chat
- `POST /api/v1/chat` : Envoyer une question
- `POST /api/v1/chat/escalate` : Escalader vers support humain

#### Documents (Admin)
- `GET /api/v1/documents` : Lister les documents
- `POST /api/v1/documents/upload` : Upload un document
- `GET /api/v1/documents/{id}` : Détails d'un document
- `DELETE /api/v1/documents/{id}` : Supprimer un document
- `POST /api/v1/documents/{id}/reprocess` : Retraiter un document

#### Admin
- `GET /api/v1/admin/system-info` : Infos système
- `GET /api/v1/admin/cache/stats` : Statistiques cache
- `POST /api/v1/admin/cache/clear` : Vider le cache
- `POST /api/v1/admin/vector-store/rebuild` : **Rebuild index + nettoyage orphelins**
- `GET /api/v1/admin/audit-log` : Logs d'audit

#### Auth
- `POST /api/v1/auth/login` : Connexion admin
- `POST /api/v1/auth/refresh` : Rafraîchir le token

#### Health
- `GET /api/v1/health` : Health check complet
- `GET /api/v1/health/database` : Santé de la BD
- `GET /api/v1/health/cache` : Santé du cache

## 📊 Performance

### Métriques Cibles
- **Temps de réponse chat** : < 3 secondes
- **Capacité documents** : 1 000 à 20 000 documents
- **Utilisateurs simultanés** : 50
- **Taille max document** : 100 MB
- **Chunks max par document** : 2 000

### Optimisations Implémentées
- Cache LRU avec TTL pour réponses chat
- Mode WAL SQLite pour concurrence
- Batch processing pour embeddings
- Index FAISS optimisé (FlatL2)
- **Nettoyage automatique des chunks orphelins**
- Scoring adaptatif avec boost nom de fichier
- Queue asynchrone séquentielle pour ingestion
- Retry logic avec backoff exponentiel

## 🔒 Sécurité

### Mesures Implémentées
- **Authentification** : JWT avec tokens signés
- **Passwords** : Hash bcrypt avec salt
- **Rate Limiting** : Adaptatif par type utilisateur
- **CORS** : Configuré selon environnement
- **Validation** : Pydantic sur tous les inputs
- **Injection Prevention** : Prompts sanitizés
- **Logs RGPD** : Pas de log des questions utilisateurs
- **Isolation** : Déploiement sur infrastructure dédiée

### Conformité
- RGPD : Données en local uniquement
- Confidentialité : Aucune donnée externe
- Audit trail : Logs d'actions admin complets

## 🐛 Troubleshooting

### Problèmes Courants

#### 1. Erreur de connexion à Mistral API

```bash
# Vérifier la clé API
echo $MISTRAL_API_KEY

# Tester manuellement
curl -H "Authorization: Bearer $MISTRAL_API_KEY" https://api.mistral.ai/v1/models
```

#### 2. Base de données verrouillée

```bash
# Vérifier le mode WAL
sqlite3 data/sqlite/mimir.db "PRAGMA journal_mode;"

# Activer WAL si nécessaire
sqlite3 data/sqlite/mimir.db "PRAGMA journal_mode=WAL;"
```

#### 3. Index FAISS corrompu

```bash
# Supprimer et reconstruire
rm data/faiss/index.bin data/faiss/metadata.pkl

# Retraiter tous les documents via l'admin
# Endpoint: POST /api/v1/documents/{id}/reprocess
```

#### 4. Cache plein

```bash
# Vider le cache via API
curl -X POST http://localhost:8000/api/v1/admin/cache/clear \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

#### 5. Chunks orphelins après suppression de documents

Les chunks orphelins sont des chunks vectoriels qui existent dans FAISS mais dont le document parent a été supprimé de la base de données. Ils peuvent causer l'apparition de résultats fantômes dans les recherches.

**Symptômes :**
- Documents supprimés qui apparaissent encore dans les résultats de recherche
- Messages d'erreur "Document not found" dans les logs

**Solution :**
```bash
# Via l'interface admin : bouton "Rebuild Index"
# Ou via API :
curl -X POST http://localhost:8000/api/v1/admin/vector-store/rebuild \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Le rebuild effectue automatiquement :
- ✅ Détection des chunks orphelins
- ✅ Marquage comme supprimés  
- ✅ Optimisation de l'index FAISS
- ✅ Suppression physique des chunks deleted

### Logs

```bash
# Backend logs
tail -f backend/logs/app.log

# Frontend logs (envoyés au backend)
tail -f backend/logs/frontend.log

# Filtrer par niveau
grep "ERROR" backend/logs/app.log
```

## 📖 Documentation Complémentaire

- [mimir-codeguide.md](./mimir-codeguide.md) : Guide détaillé du code et de l'architecture
- [mimir-cahier-charges.md](./mimir-cahier-charges.md) : Cahier des charges complet
- [mimir-hld.md](./mimir-hld.md) : High-Level Design
- [mimir-lld.md](./mimir-lld.md) : Low-Level Design
- [mimir-implementation-plan.md](./mimir-implementation-plan.md) : Plan d'implémentation

## 🤝 Contribution

Ce projet est propriétaire et destiné à un usage interne entreprise.

### Standards de Code
- **Python** : PEP 8, type hints, docstrings
- **JavaScript** : ESLint, Prettier
- **Commits** : Conventional Commits
- **Tests** : Couverture > 80%

## 📝 License

Proprietary - Usage interne entreprise uniquement

## 👥 Support

Pour toute question ou problème :
- Email : support@votre-entreprise.com
- Documentation : `/docs`
- Issues : Gestionnaire de tickets interne

---

**Développé avec ❤️ pour optimiser la productivité de votre entreprise**