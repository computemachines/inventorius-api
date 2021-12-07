![Code coverage badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fgist.githubusercontent.com%2Fcomputemachines%2Fc6358499cfa820bcffe8535e6cabd586%2Fraw%2Fcoverage-inventory-v2-api-badge.json)


Run dev server, (windows powershell): 
```powershell
$Env:FLASK_ENV = "development"
$Env:FLASK_APP = "inventory"
python -m flask run -p 8081
```

Run tests with
```sh
pytest
coverage run --source=inventory -m pytest
```