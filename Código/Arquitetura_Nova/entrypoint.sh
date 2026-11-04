#!/bin/sh
set -e

MODO="${APP_MODE:-desenvolvimento}"

for arg in "$@"; do
    case "$arg" in
        --produção|--producao|-p)
            MODO="produção"
            ;;
        --desenvolvimento|-d)
            MODO="desenvolvimento"
            ;;
    esac
done

echo ">>> [Entrypoint] Criando as Migrações"
python manage.py makemigrations

echo ">>> [Entrypoint] Aplicando migrações do banco de dados..."
python manage.py migrate

echo ">>> [Entrypoint] Verificando regra de superusuário (máximo 1)..."
python /app/garantir_superuser.py

echo ">>> [Entrypoint] Verificando provisionamento do ChirpStack (Gateway, Perfil, App, Webhook e Sensor)..."
python /app/garantir_chirpstack.py

if [ "$MODO" = "produção" ] || [ "$MODO" = "producao" ]; then
    echo ">>> [Entrypoint] Iniciando servidor Django em modo PRODUÇÃO (--noreload)..."
    exec python manage.py runserver 0.0.0.0:8000 --noreload
else
    echo ">>> [Entrypoint] Iniciando servidor Django em modo DESENVOLVIMENTO (auto-reload ativo)..."
    exec python manage.py runserver 0.0.0.0:8000
fi
