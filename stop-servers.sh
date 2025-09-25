#!/bin/bash

echo "🛑 Arrêt des serveurs Mimir..."

# Fonction pour arrêter un processus avec gestion d'erreur
stop_process() {
    local pid_file=$1
    local process_name=$2

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p $pid > /dev/null 2>&1; then
            echo "🔴 Arrêt du $process_name (PID: $pid)..."
            kill $pid

            # Attendre que le processus s'arrête
            local count=0
            while ps -p $pid > /dev/null 2>&1 && [ $count -lt 10 ]; do
                sleep 1
                ((count++))
            done

            # Forcer l'arrêt si nécessaire
            if ps -p $pid > /dev/null 2>&1; then
                echo "⚡ Arrêt forcé du $process_name..."
                kill -9 $pid
            fi

            echo "✅ $process_name arrêté"
        else
            echo "⚠️  $process_name n'était pas en cours d'exécution (PID: $pid)"
        fi
        rm -f "$pid_file"
    else
        echo "ℹ️  Aucun fichier PID trouvé pour $process_name"
    fi
}

# Créer le répertoire des logs s'il n'existe pas
mkdir -p logs

# Arrêter le backend
stop_process "logs/backend.pid" "backend"

# Arrêter le frontend
stop_process "logs/frontend.pid" "frontend"

# Nettoyer les processus orphelins éventuels
echo "🧹 Nettoyage des processus orphelins..."

# Rechercher et arrêter les processus uvicorn
UVICORN_PIDS=$(pgrep -f "uvicorn main:app")
if [ ! -z "$UVICORN_PIDS" ]; then
    echo "🔄 Arrêt des processus uvicorn orphelins..."
    echo $UVICORN_PIDS | xargs kill 2>/dev/null || true
fi

# Rechercher et arrêter les processus vite
VITE_PIDS=$(pgrep -f "vite.*dev")
if [ ! -z "$VITE_PIDS" ]; then
    echo "🔄 Arrêt des processus vite orphelins..."
    echo $VITE_PIDS | xargs kill 2>/dev/null || true
fi

# Rechercher et arrêter les processus node liés à vite
NODE_VITE_PIDS=$(pgrep -f "node.*vite")
if [ ! -z "$NODE_VITE_PIDS" ]; then
    echo "🔄 Arrêt des processus node/vite orphelins..."
    echo $NODE_VITE_PIDS | xargs kill 2>/dev/null || true
fi

echo ""
echo "✅ Tous les serveurs ont été arrêtés"
echo "📝 Les logs sont conservés dans logs/"