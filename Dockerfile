FROM node:24-trixie-slim@sha256:ac39e4b5fcb2b1b34b20364fd58b2e898f3bb80731ee6f62a7536f9df3d6aadc AS provider-clis

ARG TARGETARCH=amd64
RUN test "$TARGETARCH" = "amd64"

WORKDIR /provider-clis
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && /provider-clis/node_modules/@anthropic-ai/claude-code-linux-x64/claude --version \
    && /provider-clis/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex --version


FROM python:3.12-slim-trixie@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ARG VCS_REF=development
ARG VERSION=1.0.0
ARG TARGETARCH=amd64

# The paired Mobius target image is currently amd64-only. Fail at build time
# instead of publishing an ARM worker that cannot recover an ARM target.
RUN test "$TARGETARCH" = "amd64"

LABEL org.opencontainers.image.title="Mobius Recovery Worker" \
      org.opencontainers.image.source="https://github.com/mobius-os/mobius-recovery" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"

# Claude ships as a standalone binary. Codex's native binary resolves its
# bundled helper resources relative to this vendor directory, so neither npm
# package wrapper nor Node belongs in the runtime image.
COPY --from=provider-clis \
  /provider-clis/node_modules/@anthropic-ai/claude-code-linux-x64/claude \
  /usr/local/bin/claude
COPY --from=provider-clis \
  /provider-clis/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl \
  /opt/codex
RUN ln -s /opt/codex/bin/codex /usr/local/bin/codex

WORKDIR /app

COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes \
      --requirement /app/requirements.lock \
    && groupadd --gid 10001 recovery \
    && useradd --uid 10001 --gid 10001 --home-dir /state \
      --no-create-home --shell /usr/sbin/nologin recovery \
    && mkdir -p /state /app /usr/local/bin \
    && chown recovery:recovery /state \
    && chmod 0700 /state

COPY recovery_worker /app/recovery_worker
COPY bin/mobius-target /usr/local/bin/mobius-target
COPY VERSION /app/VERSION

# Build identity is created inside the image and is never read from runtime env.
RUN case "$VCS_REF" in (*[!A-Za-z0-9._:-]*|'') exit 2;; esac \
    && printf '%s\n' "$VCS_REF" > /app/BUILD_REVISION \
    && chmod 0555 /usr/local/bin/mobius-target \
    && find /app -type d -exec chmod 0555 {} + \
    && find /app -type f -exec chmod 0444 {} + \
    && find / -xdev -type f -perm /6000 -exec chmod a-s {} + \
    && ! command -v sudo \
    && ! command -v railway \
    && ! command -v docker

ENV PORT=8000 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOBIUS_RECOVERY_STATE_DIR=/state

USER 10001:10001
EXPOSE 8000

ENTRYPOINT ["python", "-m", "recovery_worker"]
