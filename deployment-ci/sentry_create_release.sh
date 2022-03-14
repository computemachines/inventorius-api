#! /usr/bin/bash

. deployment-ci/inventorius-frontend_secrets.sh
export SENTRY_RELEASE_VERSION=$(node -e "console.log(require('./package.json').version)")
npx sentry-cli --auth-token "$SENTRY_AUTH_TOKEN" releases -o "$SENTRY_ORG" new -p "$SENTRY_PROJECT" "$SENTRY_RELEASE_VERSION"
