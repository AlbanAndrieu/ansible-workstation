#!/usr/bin/env bash
# Rotate the workstation Redis password and give LiteLLM the same one, without printing it.
# Run by the operator: agents may not read .env files. Backups: <file>.bak-<stamp>.
set -euo pipefail

nc_dir=/workspace/users/albandrieu30/nabla-compose
nc_env=$nc_dir/.env
ll_env=$HOME/.litellm/.env
stamp=$(date +%Y%m%d-%H%M%S)
url_re="^REDIS_URL=([\"']?)redis://([^:@/]*):[^@]*@"

# Compose prefers exported variables to .env: an exported value would silently win over the rotation.
for var in REDIS_AUTH REDIS_URL DATABASE_URL; do
  [ -z "${!var:-}" ] || {
    echo "$var is exported by this shell and overrides the .env files: run from a shell without it" >&2
    exit 1
  }
done

[ "$(grep -cE "$url_re" "$ll_env")" = 1 ] || {
  echo "REDIS_URL in $ll_env is not a single redis://[user]:password@host line: nothing changed" >&2
  exit 1
}
[ "$(grep -c '^REDIS_AUTH=' "$nc_env")" -le 1 ] || {
  echo "several REDIS_AUTH lines in $nc_env: nothing changed" >&2
  exit 1
}

cp -p "$nc_env" "$nc_env.bak-$stamp"
cp -p "$ll_env" "$ll_env.bak-$stamp"
pw=$(openssl rand -hex 32)
if grep -q '^REDIS_AUTH=' "$nc_env"; then
  sed -i "s|^REDIS_AUTH=.*|REDIS_AUTH=$pw|" "$nc_env"
else
  printf 'REDIS_AUTH=%s\n' "$pw" >>"$nc_env"
fi
sed -i -E "s#$url_re#REDIS_URL=\\1redis://\\2:$pw@#" "$ll_env"
[ "$(grep -c "$pw" "$nc_env")" = 1 ] && [ "$(grep -c "$pw" "$ll_env")" = 1 ] || {
  echo "password not written exactly once in each file; restore the .bak-$stamp copies" >&2
  exit 1
}
unset pw
chmod 600 "$nc_env" "$ll_env"
echo "password rotated in both files (backups .bak-$stamp)"

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
