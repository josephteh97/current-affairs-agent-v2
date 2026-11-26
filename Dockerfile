# ARIA in a locked-down container (SECURITY.md §4 "Isolation").
#
# Base image pinned by digest, not just tag: a tag can be re-pointed to a
# different image; a digest cannot. Update deliberately:
#   docker buildx imagetools inspect python:3.11-slim   # copy the new Digest
FROM python:3.11-slim@sha256:61e01f72680f86a5279ad510818ab7b2ee9f049822589d4e34e33e044360356c

# Unprivileged user with no login shell and no home directory contents.
# Strip setuid/setgid bits from every binary, so no program in the image can
# raise privileges. (This replaces `no-new-privileges`, which on some
# AppArmor-enabled hosts blocks all exec — see docker-compose.yml.)
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin aria \
 && find / -xdev -perm /6000 -type f -exec chmod a-s {} + \
 && ! find / -xdev -perm /6000 -type f | grep -q .

WORKDIR /app

# Dependencies first (cached layer), verified against the hash lock.
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

# Application code only — see .dockerignore for what is excluded
# (memory, logs, .git, screenshots never enter the image).
COPY *.py skills.lock ./
COPY skills/ skills/
COPY tests/ tests/

# Code is owned by root and not writable by the runtime user;
# all mutable state goes to /data (mounted volume).
ENV ARIA_DATA_DIR=/data \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OLLAMA_URL=http://host.docker.internal:11434

USER aria
ENTRYPOINT ["python", "agent.py"]
