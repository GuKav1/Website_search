#!/usr/bin/env bash
# Actualiza o Website Search no servidor.
#   ./deploy.sh
# Envia so o codigo. NAO toca em config.json, chaves.json nem resultados/ —
# a configuracao do servidor e diferente da do Mac (la as exclusoes vêm da
# Google Sheet, aqui vêm dos ficheiros do robot).
set -euo pipefail
SV=root@94.130.173.34
DEST=/root/prospector

rsync -az --delete \
  --exclude '.git' --exclude '.venv' --exclude '.cache' --exclude 'resultados' \
  --exclude 'config.json' --exclude 'chaves.json' --exclude '__pycache__' \
  --exclude 'deploy.sh' --exclude 'app.py' \
  ./ "$SV:$DEST/"

ssh "$SV" "cd $DEST && .venv/bin/python -c 'import prospector; print(\"OK:\", len(prospector.PAISES), \"paises,\", len(prospector.NOMES), \"categorias\")'"
echo "feito — http://94.130.173.34:8000/prospector"
