FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

ENV NEXT_PUBLIC_API_URL=https://bahamut-production.up.railway.app
ENV NEXT_PUBLIC_WS_URL=wss://bahamut-production.up.railway.app/ws

RUN npm run build

ENV PORT=3000
EXPOSE 3000

CMD ["npm", "start"]
