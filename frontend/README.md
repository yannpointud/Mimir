# Mimir Frontend

Interface utilisateur React pour l'assistant documentaire intelligent Mimir.

## 🚀 Fonctionnalités

### Interface Chat
- **Conversation intelligente** : Interface de chat intuitive avec support Markdown
- **Sources citées** : Affichage des sources avec scores de pertinence
- **Escalade humaine** : Bouton pour contacter le support avec historique automatique
- **Messages typés** : Support des messages utilisateur, assistant, système et erreur
- **Auto-scroll** : Défilement automatique vers les nouveaux messages
- **Copie facile** : Bouton de copie pour les réponses de l'assistant

### Interface Administration
- **Authentification JWT** : Connexion sécurisée pour les administrateurs
- **Gestion des documents** : Upload, suppression, protection des documents
- **Monitoring système** : Surveillance en temps réel de la santé du système
- **Configuration** : Visualisation en lecture seule des paramètres système
- **Upload par glisser-déposer** : Interface moderne pour l'ajout de documents
- **Statistiques** : Tableaux de bord avec métriques en temps réel

## 🛠 Technologies

- **React 18** - Interface utilisateur moderne
- **Vite** - Build tool rapide avec HMR
- **Tailwind CSS** - Framework CSS utilitaire
- **React Router** - Navigation côté client
- **Axios** - Client HTTP pour les appels API
- **React Markdown** - Rendu des réponses Markdown
- **React Dropzone** - Upload de fichiers par glisser-déposer
- **Lucide React** - Icônes modernes
- **Vitest** - Framework de test

## 📦 Installation

```bash
# Installer les dépendances
npm install

# Démarrer en mode développement
npm run dev

# Construire pour la production
npm run build

# Prévisualiser la build de production
npm run preview

# Lancer les tests
npm run test

# Tests avec interface graphique
npm run test:ui

# Tests avec couverture
npm run test:coverage
```

## 🔧 Configuration

### Variables d'environnement

Copiez `.env.example` vers `.env` et ajustez les valeurs :

```bash
# API Configuration
VITE_API_BASE_URL=/api/v1

# Application
VITE_APP_NAME=Mimir
VITE_APP_VERSION=1.0.0
VITE_APP_DESCRIPTION="Assistant documentaire intelligent"
```

### Proxy de développement

Le serveur de développement Vite est configuré pour proxifier les appels API vers `http://localhost:8000`.

## 📁 Structure du projet

```
frontend/
├── src/
│   ├── components/           # Composants React
│   │   ├── Chat/            # Interface de chat
│   │   ├── Admin/           # Interface d'administration
│   │   └── Common/          # Composants partagés
│   ├── hooks/               # Hooks React personnalisés
│   ├── services/            # Services API
│   ├── utils/               # Fonctions utilitaires
│   ├── test/                # Tests et configuration
│   └── App.jsx              # Composant racine
├── public/                  # Assets statiques
└── dist/                    # Build de production
```

## 🎨 Design System

### Couleurs
- **Primary** : Bleu (variants 50-900)
- **Gray** : Gris neutre (variants 50-900)
- **Success** : Vert pour les états positifs
- **Warning** : Jaune pour les avertissements
- **Error** : Rouge pour les erreurs

### Composants CSS
- **Boutons** : `.btn-primary`, `.btn-secondary`, `.btn-danger`
- **Inputs** : `.input-field`
- **Cards** : `.card`
- **Messages** : `.message-user`, `.message-assistant`

## 🔒 Sécurité

### Authentification
- **JWT** stocké dans localStorage
- **Auto-refresh** des tokens expirés
- **Déconnexion automatique** en cas d'erreur 401
- **Validation côté client** des données utilisateur

### Protection des routes
- **Routes protégées** pour l'administration
- **Vérification des rôles** (admin uniquement)
- **Redirection automatique** vers login si non authentifié

## 📱 Responsive Design

L'interface est optimisée pour :
- **Mobile** : Sidebar collapsible, navigation tactile
- **Tablet** : Layout adaptatif avec colonnes flexibles
- **Desktop** : Interface complète avec sidebar fixe

## 🧪 Tests

### Structure des tests
```
src/test/
├── components/              # Tests des composants
├── utils/                   # Tests des utilitaires
└── setup.js                 # Configuration des tests
```

### Types de tests
- **Tests unitaires** : Composants individuels
- **Tests d'intégration** : Flux utilisateur complets
- **Tests utilitaires** : Fonctions helper

### Commandes de test
```bash
npm run test                 # Tests en mode watch
npm run test:ui             # Interface graphique Vitest
npm run test:coverage       # Avec rapport de couverture
```

## 🚀 Déploiement

### Build de production
```bash
npm run build
```

Le dossier `dist/` contient les assets optimisés :
- **Chunking automatique** : Vendor, utils séparés
- **Minification** : CSS et JS compressés
- **Cache busting** : Hashes pour les assets
- **Source maps** : Désactivées en production

### Optimisations
- **Lazy loading** : Chargement différé des routes
- **Code splitting** : Séparation vendor/app
- **Tree shaking** : Élimination du code mort
- **Compression gzip** : Assets compressés

## 🔧 Scripts npm

| Script | Description |
|--------|-------------|
| `dev` | Serveur de développement avec HMR |
| `build` | Build de production optimisée |
| `preview` | Prévisualisation de la build |
| `lint` | Vérification ESLint |
| `test` | Tests en mode watch |
| `test:ui` | Interface graphique des tests |
| `test:coverage` | Tests avec couverture |

## 📖 Guides de développement

### Ajouter un nouveau composant
1. Créer le fichier dans `src/components/`
2. Suivre les conventions de nommage (PascalCase)
3. Utiliser les classes Tailwind existantes
4. Ajouter les PropTypes si nécessaire
5. Créer un test associé

### Ajouter une nouvelle route
1. Créer le composant de page
2. Ajouter la route dans `App.jsx`
3. Mettre à jour la navigation si nécessaire
4. Ajouter la protection d'accès si requis

### Appels API
1. Utiliser les services dans `src/services/api.js`
2. Gérer les erreurs avec `getErrorMessage()`
3. Implémenter le loading state
4. Ajouter la gestion du cache si pertinent

## 🐛 Dépannage

### Erreurs courantes

**Erreur CORS en développement**
- Vérifier que le backend tourne sur le port 8000
- Vérifier la configuration du proxy dans `vite.config.js`

**Erreur d'authentification**
- Vérifier que le token JWT est valide
- Contrôler les en-têtes de requête
- Vérifier l'expiration du token

**Tests qui échouent**
- Vérifier les mocks dans `src/test/setup.js`
- S'assurer que les dépendances de test sont installées
- Contrôler les imports des composants testés

## 📄 Licence

Ce projet fait partie du système Mimir. Voir le fichier principal README.md pour les informations de licence.