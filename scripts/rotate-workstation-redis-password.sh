#!/usr/bin/env bash
# Rotate the workstation Redis password and give LiteLLM the same one, without printing it.
# Run by the operator: agents may not read .env files. Backups: <file>.bak-<stamp>.
set -euo pipefail

nc_dir=/workspace/users/albandrieu30/nabla-compose
ll_env=$HOME/.litellm/.env
stamp=$(date +%Y%m%d-%H%M%S)
url_re="^REDIS_URL=([\"']?)redis://([^:@/]*):[^@]*@"

# Compose prefers exported variables to .env: an exported value would silently win over the rotation.
for var in REDIS_AUTH REDIS_URL DATABASE_URL; do
  [ -z "${!var:-}" ] || {
    echo "$var is exported by this shell (profile pass/database.key.env.sh, or mise in nabla-compose):" \
      "run from a shell without it, then put the new value in the profile too" >&2
    exit 1
  }
done

# .env is what Compose reads; mise loads .env.secrets and .env.local into the shell of nabla-compose.
nc_files=("$nc_dir/.env")
for f in "$nc_dir/.env.secrets" "$nc_dir/.env.local"; do
  [ -f "$f" ] && grep -q '^REDIS_AUTH=' "$f" && nc_files+=("$f")
done

[ "$(grep -cE "$url_re" "$ll_env")" = 1 ] || {
  echo "REDIS_URL in $ll_env is not a single redis://[user]:password@host line: nothing changed" >&2
  exit 1
}
for f in "${nc_files[@]}"; do
  [ "$(grep -c '^REDIS_AUTH=' "$f")" -le 1 ] || {
    echo "several REDIS_AUTH lines in $f: nothing changed" >&2
    exit 1
  }
done

for f in "${nc_files[@]}" "$ll_env"; do
  cp -p "$f" "$f.bak-$stamp"
done
pw=$(openssl rand -hex 32)
for f in "${nc_files[@]}"; do
  if grep -q '^REDIS_AUTH=' "$f"; then
    sed -i "s|^REDIS_AUTH=.*|REDIS_AUTH=$pw|" "$f"
  else
    printf 'REDIS_AUTH=%s\n' "$pw" >>"$f"
  fi
done
sed -i -E "s#$url_re#REDIS_URL=\\1redis://\\2:$pw@#" "$ll_env"
for f in "${nc_files[@]}" "$ll_env"; do
  [ "$(grep -c "$pw" "$f")" = 1 ] || {
    echo "password not written exactly once in $f; restore the .bak-$stamp copies" >&2
    exit 1
  }
done
unset pw
chmod 600 "${nc_files[@]}" "$ll_env"
echo "password rotated in ${#nc_files[@]} nabla-compose file(s) and $ll_env (backups .bak-$stamp)"

(cd "$nc_dir" && docker compose -f docker-compose-albandrieu.yml up -d --no-deps --force-recreate redis-server)
(cd "$nc_dir/litellm" && docker compose up -d --no-deps --force-recreate litellm)

for _ in $(seq 60); do
  [ "$(docker inspect -f '{{.State.Health.Status}}' redis)" = healthy ] &&
    [ "$(docker inspect -f '{{.State.Health.Status}}' litellm-litellm-1)" = healthy ] && break
  sleep 5
done
echo "redis: $(docker inspect -f '{{.State.Health.Status}}' redis)"
echo "litellm: $(docker inspect -f '{{.State.Health.Status}}' litellm-litellm-1)"
echo "auth errors since restart: $(docker logs --since 5m litellm-litellm-1 2>&1 | grep -c 'invalid username-password' || true)"
