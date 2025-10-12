# This build supports multi-platform builds through standard Docker Buildx
# techniques, including the $TARGETPLATFORM environment variable.
FROM golang:1.23 AS builder
WORKDIR /src
COPY go.mod .
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/benchmark-server .

FROM scratch
COPY --from=builder /usr/local/bin/benchmark-server /benchmark-server
USER 1001:1001
ENTRYPOINT ["/benchmark-server"]
