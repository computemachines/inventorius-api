# ; gpg --quiet --batch --yes --decrypt --passphrase "$SECRET_PASSPHRASE" --output secrets.txt secrets.txt.gpg
# ; gpg -c secrets.txt

# [sentry]
SERVER_SENTRY_ORG="computemachines"
SERVER_SENTRY_PROJECT="inventory-demo-frontend-server"
CLIENT_SENTRY_ORG="computemachines"
CLIENT_SENTRY_PROJECT="inventorius-demo-frontend-client"
SENTRY_AUTH_TOKEN="3af6129d1c53480e95222864c321a67889469ac2dfba40998f8911a7e4792e39"