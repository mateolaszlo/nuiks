#!/bin/sh

set -eu

template_path="$1"
output_path="$2"
public_base_url="${STUDYVAULT_PUBLIC_BASE_URL:-http://localhost:8080}"
public_base_url="${public_base_url%/}"
redirect_uri="${public_base_url}/*"

sed \
  -e "s|__STUDYVAULT_PUBLIC_BASE_URL__|${public_base_url}|g" \
  -e "s|__STUDYVAULT_FRONTEND_REDIRECT_URI__|${redirect_uri}|g" \
  -e "s|__STUDYVAULT_FRONTEND_WEB_ORIGIN__|${public_base_url}|g" \
  "$template_path" > "$output_path"
