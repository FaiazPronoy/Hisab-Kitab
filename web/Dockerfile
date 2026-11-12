FROM node:20-alpine AS build
WORKDIR /web
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ARG NEXT_PUBLIC_API_KEY=local-dev-key
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_API_KEY=$NEXT_PUBLIC_API_KEY NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine
WORKDIR /web
# listen on every interface; by default Next binds to the container hostname, which can fail to resolve
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /web/.next/standalone ./
COPY --from=build /web/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
