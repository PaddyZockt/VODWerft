# VODWerft-Upload-Server als fertiges Image. Wird bei jedem Release automatisch gebaut (siehe .github/workflows/image.yml).
# Selbst bauen:  docker build -t vodwerft-uploader .   (im Ordner "server")
# Im Image steckt nur Programmcode. Zugangsdaten (client_secrets.json, request.token) kommen von aussen als Volume.
FROM golang:1.24-alpine AS build
RUN apk add --no-cache git \
    && git clone --depth 1 --branch v1.25.5 https://github.com/porjo/youtubeuploader.git /src
WORKDIR /src
# Im Dauerbetrieb muss ein fehlender Token zum Fehler fuehren, statt einen OAuth-Port zu oeffnen.
RUN grep -q 'randState := fmt.Sprintf' oauth.go \
    && sed -i '/randState := fmt.Sprintf/i\    if os.Getenv("YTU_NONINTERACTIVE") == "1" { return nil, errors.New("reauthentication required") }' oauth.go \
    && CGO_ENABLED=0 go build -ldflags="-X main.appVersion=v1.25.5" -o /youtubeuploader ./cmd/youtubeuploader

FROM python:3.13-alpine
RUN apk add --no-cache ca-certificates tzdata
COPY --from=build /youtubeuploader /usr/local/bin/youtubeuploader
WORKDIR /opt/uploader
COPY worker-confirmed.py /opt/uploader/worker.py
COPY resumable_upload.py bundle.py VERSION ./
LABEL org.opencontainers.image.title="VODWerft Upload-Server" \
      org.opencontainers.image.source="https://github.com/PaddyZockt/VODWerft" \
      org.opencontainers.image.licenses="MIT"
ENV PYTHONDONTWRITEBYTECODE=1 YTU_NONINTERACTIVE=1
ENTRYPOINT ["python", "-u", "/opt/uploader/worker.py"]
