import os
import django

# Configura o ambiente do Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Projeto_Me_Tornei_Um_Mestre.settings")
django.setup()

from django.contrib.auth import get_user_model

def verificar_e_gerenciar_superuser():
    User = get_user_model()
    
    # 1. Verifica se já existe qualquer superusuário no banco
    superusers = User.objects.filter(is_superuser=True)
    total_superusers = superusers.count()
    
    if total_superusers > 0:
        nomes = ", ".join(superusers.values_list('username', flat=True))
        print(f"[SUPERUSER] Já existe superusuário cadastrado ({nomes}). Criação impedida (limite: apenas 1 superusuário permitido).")
        return

    # 2. Caso não exista nenhum, cria o único superusuário
    username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin")
    email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "admin@smartcampus.com")
    password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "admin123")

    print(f"[SUPERUSER] Nenhum superusuário encontrado. Criando superusuário único '{username}'...")
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"[SUPERUSER] Superusuário '{username}' criado com sucesso!")

if __name__ == "__main__":
    verificar_e_gerenciar_superuser()
