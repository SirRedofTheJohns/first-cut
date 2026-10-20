#!/bin/sh
# Idempotent WordPress bootstrap, run by the `wpcli` service in docker-compose.
set -eu

echo "Waiting for WordPress files and database..."
until [ -f /var/www/html/wp-config.php ] && wp db check >/dev/null 2>&1; do
  sleep 3
done

if ! wp core is-installed >/dev/null 2>&1; then
  wp core install \
    --url="$WP_URL" \
    --title="First Cut Sandbox" \
    --admin_user="$WP_USER" \
    --admin_password="$WP_ADMIN_PASSWORD" \
    --admin_email="$WP_ADMIN_EMAIL" \
    --skip-email
fi

# Pretty permalinks so the REST API lives at /wp-json/ (the image already ships the .htaccess).
wp rewrite structure '/%postname%/' >/dev/null

if [ "$(wp user application-password list "$WP_USER" --name=first-cut --format=count)" = "0" ]; then
  APP_PASSWORD=$(wp user application-password create "$WP_USER" first-cut --porcelain)
  echo ""
  echo "=================================================================="
  echo " Application Password created. Add this line to your .env file:"
  echo " WP_APP_PASSWORD=$APP_PASSWORD"
  echo "=================================================================="
else
  echo "Application Password 'first-cut' already exists (WordPress only shows it once)."
  echo "To regenerate: wp user application-password delete $WP_USER --all, then rerun this service."
fi

echo "WordPress is ready at $WP_URL"
