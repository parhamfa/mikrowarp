FROM local/warp-masque-gateway:2026.7.1377.0-r11-pilot AS reference
FROM ubuntu:22.04 AS assemble
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev python3
COPY --from=reference / /out/
COPY standard/container /source/
RUN mkdir -p /out/usr/local/libexec \
    && gcc -O2 -Wall -Wextra -Werror -Wl,-z,relro,-z,now -o /out/usr/local/libexec/mikrowarp-io /source/io.c \
    && strip /out/usr/local/libexec/mikrowarp-io \
    && python3 /source/assemble.py /out \
    && chroot /out /bin/sh -ec 'cd /; sha256sum -c /usr/share/mikrowarp/warp-binaries.sha256'
FROM scratch
COPY --from=assemble /out/ /
LABEL org.opencontainers.image.title="MikroWARP Standard" \
      org.opencontainers.image.version="2026.7.1377.0-r14-standard" \
      org.opencontainers.image.description="r11-based IPv4 WARP/MASQUE gateway; administrator-owned routing"
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    MIKROWARP_INTERVAL=10 MIKROWARP_LEASE_SECONDS=60 MIKROWARP_MIN_FREE_MIB=64
VOLUME ["/var/lib/mikrowarp"]
WORKDIR /var/lib/mikrowarp/diagnostics
HEALTHCHECK --interval=15s --timeout=3s --start-period=60s --retries=2 CMD ["/usr/local/sbin/mikrowarp"]
ENTRYPOINT ["/usr/local/libexec/mikrowarp-io", "supervise", "/usr/local/lib/mikrowarp/gateway.sh"]
