FROM node:20-alpine AS build
WORKDIR /app
COPY web/package*.json ./
RUN npm ci
COPY web/ .
ARG VITE_IS_STAGING
ENV VITE_IS_STAGING=$VITE_IS_STAGING
ARG VITE_SENTRY_DSN
ENV VITE_SENTRY_DSN=$VITE_SENTRY_DSN
ARG RAILWAY_GIT_COMMIT_SHA
ARG RENDER_GIT_COMMIT
ARG GIT_COMMIT_SHA=${RAILWAY_GIT_COMMIT_SHA:-$RENDER_GIT_COMMIT}
ARG VITE_SENTRY_RELEASE
ENV VITE_SENTRY_RELEASE=${VITE_SENTRY_RELEASE:-$GIT_COMMIT_SHA}
# Source-map upload credentials (issue #233). ARG-only, never ENV: the token
# must not persist in the image. Unset => vite skips the upload entirely.
ARG SENTRY_AUTH_TOKEN
ARG SENTRY_ORG
ARG SENTRY_PROJECT
RUN npm run build

FROM nginx:alpine
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
