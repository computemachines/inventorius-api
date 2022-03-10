.PHONY: deb clean build install

PACKAGE_ROOT = ./package-root

PYTHON_DIST_PACKAGES = $(PACKAGE_ROOT)/usr/lib/python3/dist-packages/
SYSTEMD_DIRECTORY = $(PACKAGE_ROOT)/usr/lib/systemd/system
CONFIG_DIRECTORY = $(PACKAGE_ROOT)/etc/inventorius


clean:
	rm -rv dist/*
	rm -r $(PACKAGE_ROOT)/

build:
	python -m build

install:
	sudo dpkg -i dist/inventorius-api_0.3.3_all.deb

deb:
	mkdir -pv $(PACKAGE_ROOT)/DEBIAN
	cp -rv DEBIAN $(PACKAGE_ROOT)
	chmod +x $(PACKAGE_ROOT)/DEBIAN/postinst $(PACKAGE_ROOT)/DEBIAN/prerm

	mkdir -pv $(SYSTEMD_DIRECTORY)
	cp -v systemd/* $(SYSTEMD_DIRECTORY)

	mkdir -pv $(PYTHON_DIST_PACKAGES)
	pip install --target $(PYTHON_DIST_PACKAGES) $(wildcard dist/inventorius_api-*-none-any.whl)

	mkdir -pv $(CONFIG_DIRECTORY)
	cp -v $(wildcard config/*) $(CONFIG_DIRECTORY)

	dpkg-deb --build $(PACKAGE_ROOT)/ dist