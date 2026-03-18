FROM node:20-slim AS builder

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Build-time env vars (baked into client JS)
ARG NEXT_PUBLIC_API_URL=https://your-api-domain.railway.app
ARG NEXT_PUBLIC_MOCK_MODE=false
ARG NEXT_PUBLIC_REFRESH_INTERVAL=5000

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_MOCK_MODE=$NEXT_PUBLIC_MOCK_MODE
ENV NEXT_PUBLIC_REFRESH_INTERVAL=$NEXT_PUBLIC_REFRESH_INTERVAL

RUN npm run build

# Production image
FROM node:20-slim AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN adduser --disabled-password --gecos '' nextuser

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

USER nextuser

EXPOSE 3000

CMD ["node", "server.js"]
