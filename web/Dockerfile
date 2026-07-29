FROM node:20-alpine AS build
WORKDIR /app
COPY web/package*.json ./
RUN npm ci
COPY web/ .
ARG VITE_IS_STAGING
ENV VITE_IS_STAGING=$VITE_IS_STAGING
ARG VITE_SENTRY_DSN
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
ARG VITE_SENTRY_RELEASE
ENV VITE_SENTRY_RELEASE=$VITE_SENTRY_RELEASE
RUN npm run build

FROM nginx:alpine
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
