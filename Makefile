.PHONY: deb clean build

PYTHON_DIST_PACKAGES = package-root/usr/lib/python3/dist-packages/

clean:
	rm -rv dist/*
	rm -r package-root/

build:
	python -m build

deb: build
	mkdir -pv package-root/DEBIAN
	
	cp -v DEBIAN/* package-root/DEBIAN

	mkdir -pv $(PYTHON_DIST_PACKAGES)
	pip install --target $(PYTHON_DIST_PACKAGES) $(wildcard dist/inventorius_api-*-none-any.whl)

	dpkg-deb --build package-root/ dist
