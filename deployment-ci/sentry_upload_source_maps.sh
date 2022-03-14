#! /usr/bin/sh

. deployment-ci/inventorius-frontend_secrets.sh
export SENTRY_RELEASE_VERSION=$(node -e "console.log(require('./package.json').version)")
npx sentry-cli --auth-token "$SENTRY_AUTH_TOKEN" releases -o "$SENTRY_ORG" -p "$SENTRY_PROJECT" files "$SENTRY_RELEASE_VERSION" \
  upload-sourcemaps --bundle dist/server.bundle.js --bundle-sourcemap dist/server.bundle.js.map --validate
