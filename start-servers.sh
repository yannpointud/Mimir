#!/bin/bash

echo "🚀 Démarrage des serveurs Mimir..."

# Vérifier si les processus sont déjà en cours
if pgrep -f "uvicorn main:app" > /dev/null; then
    echo "⚠️  Le backend semble déjà en cours d'exécution"
fi

if pgrep -f "vite.*dev" > /dev/null; then
    echo "⚠️  Le frontend semble déjà en cours d'exécution"
fi

# Créer le répertoire des logs s'il n'existe pas
mkdir -p logs

echo "📡 Démarrage du backend (port 8000)..."
cd /home/boby/Mimir/backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 > ../logs/uvicorn.log 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > ../logs/backend.pid
echo "✅ Backend démarré (PID: $BACKEND_PID)"

# Attendre que le backend soit prêt
echo "⏳ Attente du backend..."
sleep 3

echo "🎨 Démarrage du frontend (port 3000)..."
cd /home/boby/Mimir/frontend
npm run dev > ../logs/vite.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
echo "✅ Frontend démarré (PID: $FRONTEND_PID)"

echo ""
echo "🎉 Serveurs démarrés avec succès!"
echo "📱 Frontend: http://localhost:3000"
echo "🔧 Backend API: http://localhost:8000"
echo "📖 Documentation API: http://localhost:8000/docs"
echo ""
echo "📋 Pour arrêter les serveurs: ./stop-servers.sh"
echo "📝 Logs disponibles dans:"
echo "   - Backend application: backend/logs/ (app.log, debug.log, error.log, frontend.log)"
echo "   - Serveurs développement: logs/ (uvicorn.log, vite.log)"
echo "   - PIDs: logs/ (backend.pid, frontend.pid)"