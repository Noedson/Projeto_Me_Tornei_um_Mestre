FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --legacy-peer-deps && npm install --no-save pg tsx typescript

COPY . .

EXPOSE 4000

CMD ["sh", "-c", "node provisionar_arquitetura_velha.js & npx tsx src/server.ts"]

