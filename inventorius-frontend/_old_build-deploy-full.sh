#!/bin/bash --init-file

DOMAINS="-d inventory.computemachines.com -d inventori.us"
EMAIL=tparker@computemachines.com

cd /root
rm -r inventorius # fresh install
rm inventorius-frontend-package.tar.gz

echo "---- Checking user -------"
if ! id www-uwsgi-inventorius-api &>/dev/null
then
  echo "---- Creating user for web process ----"
  useradd -M www-uwsgi-inventorius-api
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

# echo "---- Building -------------"
# mkdir -pv temp-build
# pushd temp-build

# echo "---- Building Frontend ----"
# git clone https://github.com/computemachines/inventorius-frontend.git
# pushd inventorius-frontend
# git pull
# npm ci
# npm run build:client
# npm run build:server
# cp package.json inventorius-nginx.conf package-lock.json inventorius-frontend.service dist/
# pushd dist
# tar -czf /root/inventorius/inventorius-frontend-package.tar.gz *
# popd # out dist
# popd # out inventorius-frontend
# popd # out temp-build
# echo "---- Cleaning Up ----------"
# rm -rf temp-build/

echo "---- Downloading Frontend Release ----"
wget https://github.com/computemachines/inventorius-frontend/releases/latest/download/inventorius-frontend-package.tar.gz

echo "---- Installing -----------"

echo "---- Generating Certificates ----"
systemctl stop nginx
certbot certonly -n -m $EMAIL --agree-tos --standalone $DOMAINS

echo "---- Installing Frontend --"
mkdir -pv inventorius/node-deployment
cd /root/inventorius/
tar -xzf ../inventorius-frontend-package.tar.gz -C node-deployment
cd /root/inventorius/node-deployment/
npm ci --production
cp -v inventorius-frontend.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable inventorius-frontend

echo "---- Installing NGINX conf ----"
cd /root/inventorius/node-deployment/
cp -v inventorius-nginx.conf /etc/nginx/sites-available/
rm /etc/nginx/sites-enabled/default -v
ln -sv /etc/nginx/sites-available/inventorius-nginx.conf /etc/nginx/sites-enabled/inventorius-nginx.conf

echo "---- Installing Backend ----"
cd /root/inventorius/
git clone https://github.com/computemachines/inventorius-api.git
cd /root/inventorius/inventorius-api/
chown -R www-data:www-data ../
chown -R www-uwsgi-inventorius-api:www-data .
cp inventorius-api.{service,socket} /etc/systemd/system/
systemctl daemon-reload
systemctl enable inventorius-api.service
systemctl enable inventorius-api.socket
pip install -r requirements.txt

echo "---- Starting --------------"
systemctl start inventorius-frontend
systemctl start mongod
systemctl start inventorius-api.service
systemctl start inventorius-api.socket
systemctl start nginx

echo "---- Done ------------------"