![Code coverage badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fgist.githubusercontent.com%2Fcomputemachines%2Fc6358499cfa820bcffe8535e6cabd586%2Fraw%2Fcoverage-inventory-v2-api-badge.json)


# Inventorius API backend
This is the backend component of Inventorius that interacts directly with the database. Both the frontend nodejs server and browser client (inventorius-frontend) make HTTP api queries to this service to retrieve inventory data and perform inventory operations.

## Installation instructions for *inventorius-api* only
*See [inventorius-frontend] for its installation instructions*

1. Download latest .deb packages.
```sh
$ wget ???/inventorius-api_0.3.3_all.deb
```

2. Install dependencies.
```
$ sudo apt install python3 python3-flask
```

3. Install deb package.
```sh
$ sudo dpkg -i inventorius-api_0.3.3_all.deb
```

## Directory Structure
```sh
$ tree -L 2
```
```sh
.
├── config
│   ├── inventorius-api.service
│   ├── inventorius-api.socket
│   ├── inventorius-api-uwsgi.ini
│   ├── inventorius.conf
│   └── policy.xml
├── conftest.py
├── coverage.svg
├── DEBIAN
│   ├── control
│   └── rules
├── deployment-ci
│   ├── github_id_rsa.gpg
│   ├── github_id_rsa.pub
│   ├── known_hosts
│   ├── secrets.ini
│   └── secrets.ini.gpg
├── inventorius-api_0.3.3_all.deb
├── Makefile
├── __pycache__
│   ├── conftest.cpython-38-pytest-6.2.5.pyc
│   └── conftest.cpython-38-PYTEST.pyc
├── README.md
├── requirements.txt
├── setup.cfg
├── setup.py
├── src
│   └── inventorius
└── tests
    ├── data_models_strategies.py
    ├── __init__.py
    ├── __pycache__
    ├── test_data_models.py
    ├── test_inventorius_hardcoded.py
    └── test_inventorius.py

8 directories, 27 files
```




## Encryption/Decryption Reminder
Decryption (CI)
```sh
gpg --quiet --batch --yes --decrypt --passphrase="$SECRET_PASSPHRASE" --output secrets.txt secrets.txt.gpg
```
Encryption (User)
```sh
gpg -c secrets.txt
```

## Status Codes Reminder
200 - Ok
201 - Created (success, show created resource)
204 - No Content (success, don't change view)
400 - Bad Request (Client's fault)
401 - Unauthorized (Unauthenticated)
403 - Forbidden (Authenticated, but no permissions)
404 - Not Found
405 - Method Not Allowed (resource exists but can't delete, change, etc...)
409 - Conflict (With state of target resource)
500 - Internal Server Error (Server crashed, unexpected error, etc...)

## Development Dependencies
sudo apt-get install libmagickwand-dev
ImageMagick-7.1.0-17-Q16-HDRI-x64-dll.exe

## Run dev server (Ubuntu 20.04)
```sh
$ cd src
$ FLASK_ENV="development" FLASK_APP="inventorius" python3 -m flask run -p 8081
```

## Run dev server, (windows powershell): 
*may no longer work*
```powershell
$Env:FLASK_ENV = "development"
$Env:FLASK_APP = "inventorius"
python -m flask run -p 8081
```

## Run tests
```sh
pytest
coverage run --source=inventorius -m pytest
```
