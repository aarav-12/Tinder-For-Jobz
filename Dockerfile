
# ye sb sirf image k andar hoga, jab hum is image ko run karenge tab ye commands execute hongi.


FROM node:18-alpine

WORKDIR /app

COPY package*.json ./

RUN npm ci

COPY . .

EXPOSE 5000

CMD ["node", "server.js"]
