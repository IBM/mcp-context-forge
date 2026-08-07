FROM node:22-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/conformance

ARG CONFORMANCE_REPO=https://github.com/modelcontextprotocol/conformance.git
ARG CONFORMANCE_REF=main

RUN git clone --depth 1 --branch ${CONFORMANCE_REF} ${CONFORMANCE_REPO} .
RUN sed -i \
    "s/const app = createMcpExpressApp();/const app = createMcpExpressApp({ host: '0.0.0.0', allowedHosts: ['localhost', '127.0.0.1', 'everything_server'] });/" \
    examples/servers/typescript/everything-server.ts

WORKDIR /opt/conformance/examples/servers/typescript

RUN npm ci

ENV PORT=3000

EXPOSE 3000

CMD ["npm", "start"]
