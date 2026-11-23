FROM golang:1.26-bookworm AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN go get go.mau.fi/whatsmeow@v0.0.0-20261116172437-19d61352436f github.com/mattn/go-sqlite3@latest github.com/skip2/go-qrcode@latest \
 && go mod tidy \
 && CGO_ENABLED=1 go build -o /out/silo-wa-sync .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 1000 silo
COPY --from=build /out/silo-wa-sync /usr/local/bin/silo-wa-sync
USER silo
EXPOSE 18766
ENTRYPOINT ["/usr/local/bin/silo-wa-sync"]
