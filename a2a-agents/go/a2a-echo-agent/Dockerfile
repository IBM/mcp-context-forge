# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.
FROM golang:1.24.4 AS builder
ENV PATH=/usr/local/go/bin:$PATH
WORKDIR /src
COPY go.mod ./
COPY go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/a2a-echo-agent .

# Use alpine so basic tooling (busybox/wget) exists for container healthchecks.
FROM alpine:3.20
RUN adduser -D -u 1001 app
COPY --from=builder /usr/local/bin/a2a-echo-agent /usr/local/bin/a2a-echo-agent
USER 1001:1001
EXPOSE 9100
ENTRYPOINT ["/usr/local/bin/a2a-echo-agent"]
