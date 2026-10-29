"""
Script de Retreinamento e Treinamento Oficial do Agente Inteligente.
ATENÇÃO: O pipeline oficial do projeto foi consolidado na Versão 4 ('treinar_agente_v4.py').
Este arquivo delega automaticamente a execução para 'treinar_agente_v4.py',
garantindo compatibilidade com chamadas manuais e scripts legados.
"""
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SCRIPT_V4 = BASE_DIR / "treinar_agente_v4.py"

def main():
    print("=" * 65)
    print(">>> [Retreino Agente] Executando pipeline oficial V4...")
    print(f">>> Delegando execução para: {SCRIPT_V4.name}")
    print("=" * 65)
    
    comando = [sys.executable, str(SCRIPT_V4)] + sys.argv[1:]
    resultado = subprocess.run(comando, cwd=str(BASE_DIR))
    sys.exit(resultado.returncode)

if __name__ == "__main__":
    main()