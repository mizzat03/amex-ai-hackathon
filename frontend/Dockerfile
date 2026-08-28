FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_AMEX_API_URL=http://localhost:8000/api/v1
ARG NEXT_PUBLIC_AMEX_DATA_MODE=live
ENV NEXT_PUBLIC_AMEX_API_URL=$NEXT_PUBLIC_AMEX_API_URL \
    NEXT_PUBLIC_AMEX_DATA_MODE=$NEXT_PUBLIC_AMEX_DATA_MODE \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
