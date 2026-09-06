# Download through signed APT metadata without installing the desktop package.
FROM ubuntu:22.04 AS vendor
ARG WARP_VERSION=2026.7.1377.0
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg \
       | gpg --dearmor --yes -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg \
    && printf '%s\n' 'deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ jammy main' \
       > /etc/apt/sources.list.d/cloudflare-client.list \
    && apt-get update \
    && mkdir /download /package /out \
    && cd /download \
    && apt-get download "cloudflare-warp=$WARP_VERSION" \
    && dpkg-deb -x cloudflare-warp_*.deb /package \
    && mkdir -p /out/usr/bin /out/usr/share/mikrowarp /out/usr/share/doc \
    && cp /package/bin/warp-cli /package/bin/warp-svc \
          /package/bin/warp-diag /package/bin/warp-dex /out/usr/bin/ \
    && cp -a /package/usr/share/doc/cloudflare-warp /out/usr/share/doc/ \
    && dpkg-deb -f cloudflare-warp_*.deb Package Version Architecture > /out/usr/share/mikrowarp/vendor-package.txt \
    && sha256sum cloudflare-warp_*.deb >> /out/usr/share/mikrowarp/vendor-package.txt \
    && cd /out \
    && sha256sum usr/bin/warp-cli usr/bin/warp-svc usr/bin/warp-diag usr/bin/warp-dex \
       > usr/share/mikrowarp/warp-binaries.sha256

FROM ubuntu:22.04 AS runtime-packages
LABEL org.opencontainers.image.title="WARP MASQUE Router Gateway" \
      org.opencontainers.image.description="Headless L3 NAT gateway using unmodified official Cloudflare WARP binaries and MASQUE" \
      org.opencontainers.image.source="local-lab"
ENV DEBIAN_FRONTEND=noninteractive

# Keep r8's Ubuntu/glibc ABI and all four headless vendor binaries, including
# diagnostics and DEX. No desktop launcher, WebKit, LLVM, or graphics stack.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl dbus iproute2 nftables bind9-dnsutils \
       libnss3 libnss3-tools libcap2-bin libpcap0.8 \
       libtss2-esys-3.0.2-0 libtss2-tctildr0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=vendor /out/ /
RUN cd / && sha256sum -c /usr/share/mikrowarp/warp-binaries.sha256 \
    && for binary in warp-cli warp-svc warp-diag warp-dex; do \
         ldd "/usr/bin/$binary" > /tmp/warp-libraries; \
         if grep -F 'not found' /tmp/warp-libraries; then exit 1; fi; \
       done \
    && rm /tmp/warp-libraries

COPY entrypoint.sh /usr/local/sbin/warp-gateway
COPY healthcheck.sh /usr/local/sbin/warp-gateway-health
COPY probe.sh /usr/local/sbin/warp-gateway-probe

RUN chmod 0755 /usr/local/sbin/warp-gateway /usr/local/sbin/warp-gateway-health /usr/local/sbin/warp-gateway-probe

FROM runtime-packages AS assemble
# Python assembles and inventories the root filesystem; it never ships.
RUN apt-get update && apt-get install -y --no-install-recommends python3
COPY assemble-runtime.py /assemble-runtime.py
RUN python3 /assemble-runtime.py \
    && chroot /rootfs /bin/sh -ec 'cd /; sha256sum -c /usr/share/mikrowarp/warp-binaries.sha256; warp-cli --version; curl --version; dig -v; getent passwd messagebus'

FROM scratch
LABEL org.opencontainers.image.title="WARP MASQUE Router Gateway" \
      org.opencontainers.image.description="Minimal Ubuntu/glibc L3 gateway using unmodified official WARP binaries and MASQUE" \
      org.opencontainers.image.source="local-lab"
COPY --from=assemble /rootfs/ /
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

ENV WARP_LIVENESS_INTERVAL=15 \
    WARP_FAILURE_THRESHOLD=3 \
    WARP_RECONNECT_INTERVAL=120 \
    WARP_CLIENT_SUBNETS=192.168.88.0/24 \
    WARP_PROBE_SOURCE=172.31.250.1/32 \
    WARP_PROBE_QUORUM=2 \
    WARP_PROBES="204:https://www.gstatic.com/generate_204 200:https://en.wikipedia.org/robots.txt 200:https://github.com/robots.txt"

VOLUME ["/var/lib/cloudflare-warp"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=2 \
  CMD ["/usr/local/sbin/warp-gateway-health"]

ENTRYPOINT ["/usr/local/sbin/warp-gateway"]
