#!/bin/bash --init-file

DOMAINS="-d computemachines.com -d inventory.computemachines.com"
EMAIL=tparker@computemachines.com

cd /root
rm -r inventory # fresh install

echo "---- Checking user -------"
if ! id www-uwsgi-inventory-api &>/dev/null
then
  echo "---- Creating user for web process ----"
  useradd -M www-uwsgi-inventory-api
fi
# if ! id masdfongodb &>/dev/null
# then
#   echo "---- Creating user for web process ----"
#   useradd -M mongodb
# fi


echo "---- Checking for NVM ----"
if [ ! -f /root/.nvm/nvm.sh ]
then
  echo "---- NVM not installed, installing ..."
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.38.0/install.sh | bash
fi
source ~/.nvm/nvm.sh
nvm install node --lts
nvm use node --lts
# npm install --global cross-env webpack-cli

echo "---- Checking for Certbot -"
if [ ! -f /usr/bin/certbot ]
then
  snap install --classic certbot
  ln -s /snap/bin/certbot /usr/bin/certbot
fi

echo "---- apt install ----------"
apt install -y uwsgi-core uwsgi-plugin-python3 nginx python3-pip

echo "---- installing mongodb ---"
if [ ! -f /usr/bin/mongod ]
then
  apt install -y libcurl4 openssl liblzma5
  wget -qO - https://www.mongodb.org/static/pgp/server-4.4.asc | sudo apt-key add -
  echo "deb [ arch=amd64,arm64 ] https://repo.mongodb.org/apt/ubuntu focal/mongodb-org/4.4 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-4.4.list
  apt update
  apt install -y mongodb-org
  systemctl enable mongod.service # this should have been done by the official installer.
  chown -vR mongodb:mongodb /var/log/mongodb /var/lib/mongodb
fi

echo "---- Building -------------"
mkdir -pv temp-build
pushd temp-build

echo "---- Building Frontend ----"
git clone https://github.com/computemachines/inventory-frontend.git
pushd inventory-frontend
git pull
npm ci
npm run build:client
npm run build:server
cp package.json inventory-nginx.conf package-lock.json inventory-frontend.service dist/
pushd dist
tar -czf /root/inventory/inventory-frontend-package.tar.gz *
popd # out dist
popd # out inventory-frontend
popd # out temp-build
echo "---- Cleaning Up ----------"
rm -rf temp-build/

echo "---- Installing -----------"

echo "---- Generating Certificates ----"
systemctl stop nginx
certbot certonly -n -m $EMAIL --agree-tos --standalone $DOMAINS

echo "---- Installing Frontend --"
mkdir -pv inventory/node-deployment
pushd inventory
tar -xzf ../inventory-frontend-package.tar.gz -C node-deployment
pushd node-deployment
npm ci --production
cp -v inventory-frontend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable inventory-frontend
popd

echo "---- Installing NGINX conf ----"
pushd node-deployment
cp -v inventory-nginx.conf /
popd

echo "---- Installing Backend ----"
git clone https://github.com/computemachines/inventory-api.git
pushd inventory-api
git pull
chown -Rv www-data:www-data ../
chown -Rv www-uwsgi-inventory-api:www-data .
cp inventory-api.{service,socket} /etc/systemd/system/
systemctl daemon-reload
systemctl enable inventory-api.service
systemctl enable inventory-api.socket
pip install -r requirements.txt
popd

popd
echo "---- Starting --------------"
systemctl start inventory-frontend
systemctl start mongod
systemctl start inventory-api.service
systemctl start inventory-api.socket
systemctl start nginx

echo "---- Done ------------------"