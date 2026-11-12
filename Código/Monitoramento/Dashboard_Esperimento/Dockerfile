FROM node:24-alpine

WORKDIR /app

COPY package*.json ./

RUN npm install --legacy-peer-deps && npm install --legacy-peer-deps recharts lucide-react
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]