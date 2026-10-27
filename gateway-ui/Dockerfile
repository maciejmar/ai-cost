FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Rewrites (/api, /v1 → bramka) są wkompilowane w build — adres podajemy jako build-arg
ARG GATEWAY_INTERNAL_URL=http://gateway:8090
ENV GATEWAY_INTERNAL_URL=$GATEWAY_INTERNAL_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:26-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3100 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
USER node
EXPOSE 3100
CMD ["node", "server.js"]
