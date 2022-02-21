![Code coverage badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fgist.githubusercontent.com%2Fcomputemachines%2Fc6358499cfa820bcffe8535e6cabd586%2Fraw%2Fcoverage-inventorius-v2-api-badge.json)

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

## System Dependencies
sudo apt-get install libmagickwand-dev
ImageMagick-7.1.0-17-Q16-HDRI-x64-dll.exe


## Run dev server, (windows powershell): 
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