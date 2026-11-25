FROM --platform=$BUILDPLATFORM golang:1.26-bookworm AS build
ARG TARGETOS=linux
ARG TARGETARCH
WORKDIR /src
RUN if [ "$TARGETARCH" = "amd64" ] && [ "$(dpkg --print-architecture)" != "amd64" ]; then \
      apt-get update && apt-get install -y --no-install-recommends gcc-x86-64-linux-gnu libc6-dev-amd64-cross && rm -rf /var/lib/apt/lists/*; \
    elif [ "$TARGETARCH" = "arm64" ] && [ "$(dpkg --print-architecture)" != "arm64" ]; then \
      apt-get update && apt-get install -y --no-install-recommends gcc-aarch64-linux-gnu libc6-dev-arm64-cross && rm -rf /var/lib/apt/lists/*; \
    fi
COPY go.mod ./
COPY main.go ./
RUN go get go.mau.fi/whatsmeow@v0.0.0-20261116172437-19d61352436f github.com/mattn/go-sqlite3@latest github.com/skip2/go-qrcode@latest \
 && go mod tidy \
 && CC_BIN="gcc" \
 && if [ "$TARGETARCH" = "amd64" ] && [ "$(dpkg --print-architecture)" != "amd64" ]; then CC_BIN="x86_64-linux-gnu-gcc"; fi \
 && if [ "$TARGETARCH" = "arm64" ] && [ "$(dpkg --print-architecture)" != "arm64" ]; then CC_BIN="aarch64-linux-gnu-gcc"; fi \
 && CC="$CC_BIN" CGO_ENABLED=1 GOOS="$TARGETOS" GOARCH="$TARGETARCH" go build -o /out/silo-wa-sync .

FROM gcr.io/distroless/base-debian12:nonroot
COPY --from=build /out/silo-wa-sync /usr/local/bin/silo-wa-sync
EXPOSE 18766
ENTRYPOINT ["/usr/local/bin/silo-wa-sync"]
