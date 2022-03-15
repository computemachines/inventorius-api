#! /usr/bin/sh

. deployment-ci/inventorius-frontend_secrets.sh
export SENTRY_RELEASE_VERSION=$(node -e "console.log(require('./package.json').version)")
npx sentry-cli --auth-token "$SENTRY_AUTH_TOKEN" releases -o "$SERVER_SENTRY_ORG" -p "$SERVER_SENTRY_PROJECT" files "server-$SENTRY_RELEASE_VERSION" \
  upload-sourcemaps --bundle dist/server.bundle.js --bundle-sourcemap dist/server.bundle.js.map --validate --url-prefix /usr/lib/inventorius-frontend/
npx sentry-cli --auth-token "$SENTRY_AUTH_TOKEN" releases -o "$CLIENT_SENTRY_ORG" -p "$CLIENT_SENTRY_PROJECT" files "client-$SENTRY_RELEASE_VERSION" \
  upload-sourcemaps --bundle dist/assets/client.bundle.js --bundle-sourcemap dist/assets/client.bundle.js.map --validate --url-prefix /assets
