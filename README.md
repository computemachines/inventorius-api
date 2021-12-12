![Code coverage badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fgist.githubusercontent.com%2Fcomputemachines%2Fc6358499cfa820bcffe8535e6cabd586%2Fraw%2Fcoverage-inventory-v2-api-badge.json)


## System Dependencies
sudo apt-get install libmagickwand-dev
ImageMagick-7.1.0-17-Q16-HDRI-x64-dll.exe


## Run dev server, (windows powershell): 
```powershell
$Env:FLASK_ENV = "development"
$Env:FLASK_APP = "inventory"
python -m flask run -p 8081
```

## Run tests
```sh
pytest
coverage run --source=inventory -m pytest
```