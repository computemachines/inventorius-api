#! /usr/bin/bash

. deployment-ci/inventorius-frontend_secrets.sh
export SENTRY_RELEASE_VERSION=$(node -e "console.log(require('./package.json').version)")
npx sentry-cli --auth-token "$SENTRY_AUTH_TOKEN" releases -o "$SERVER_SENTRY_ORG" new -p "$SERVER_SENTRY_PROJECT" "server-$SENTRY_RELEASE_VERSION"
npx sentry-cli --auth-token "$SENTRY_AUTH_TOKEN" releases -o "$CLIENT_SENTRY_ORG" new -p "$CLIENT_SENTRY_PROJECT" "client-$SENTRY_RELEASE_VERSION"
