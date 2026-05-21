FROM docker.m.daocloud.io/library/node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install
COPY . .
RUN chmod -R +x node_modules/.bin && npm run build
FROM docker.m.daocloud.io/library/nginx:1.25-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
