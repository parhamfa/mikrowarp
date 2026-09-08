# Historical reference build; see docs/building.md for the pinned release base.
FROM local/warp-masque-gateway:2026.7.1377.0-r10
COPY --chmod=0755 entrypoint.sh /usr/local/sbin/warp-gateway-pilot
LABEL org.opencontainers.image.version="2026.7.1377.0-r11-pilot"
ENTRYPOINT ["/usr/local/sbin/warp-gateway-pilot"]
