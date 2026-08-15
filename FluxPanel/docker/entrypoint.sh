#!/bin/sh
set -eu

# Storage is a persistent Docker volume. Fix ownership after image updates so
# Laravel can continue to write logs, cache files, and customer uploads.
chown -R www-data:www-data /var/www/html/storage /var/www/html/bootstrap/cache

# Composer scripts are intentionally deferred until runtime because the
# production APP_KEY is supplied by Compose's env_file, not baked into the
# image during `docker build`.
php artisan package:discover --ansi

exec "$@"
