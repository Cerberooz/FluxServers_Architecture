# Production FluidPanel image. Runtime orchestration lives in the repository
# root compose.yaml; this image intentionally contains no Nginx, Certbot, or
# database service.
FROM node:22-alpine AS frontend
WORKDIR /app
COPY package.json yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile
COPY . .
RUN yarn run build:production

FROM php:8.3-apache
WORKDIR /var/www/html

RUN apt-get update \
    && apt-get install -y --no-install-recommends libzip-dev libsqlite3-dev libmariadb-dev libonig-dev \
    && docker-php-ext-install bcmath mbstring pdo_mysql pdo_sqlite zip \
    && a2enmod rewrite \
    && sed -ri 's!/var/www/html!/var/www/html/public!g' /etc/apache2/sites-available/*.conf \
    && printf '<Directory /var/www/html/public>\n    AllowOverride All\n    Require all granted\n</Directory>\n' > /etc/apache2/conf-available/fluidpanel.conf \
    && a2enconf fluidpanel \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer
COPY . .
COPY --from=frontend /app/public/assets ./public/assets
RUN composer install --no-dev --no-interaction --prefer-dist --optimize-autoloader \
    && chown -R www-data:www-data bootstrap/cache storage database

COPY docker/entrypoint.sh /usr/local/bin/fluidpanel-entrypoint
RUN chmod +x /usr/local/bin/fluidpanel-entrypoint

EXPOSE 80
ENTRYPOINT ["fluidpanel-entrypoint"]
CMD ["apache2-foreground"]
