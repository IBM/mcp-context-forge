FROM --platform=$TARGETPLATFORM golang:1.23 AS builder
WORKDIR /src
COPY go.mod .
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /usr/local/bin/benchmark-server .

FROM scratch
COPY --from=builder /usr/local/bin/benchmark-server /benchmark-server
ENTRYPOINT ["/benchmark-server"]
