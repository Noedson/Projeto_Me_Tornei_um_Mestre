#!/bin/sh
set -e

echo ">>> [Entrypoint] Aplicando migrações do banco de dados..."
python manage.py migrate

echo ">>> [Entrypoint] Verificando regra de superusuário (máximo 1)..."
python /app/garantir_superuser.py

echo ">>> [Entrypoint] Iniciando servidor Django..."
exec python manage.py runserver 0.0.0.0:8000
