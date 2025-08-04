.PHONY: deb clean build install

PACKAGE_ROOT = ./package-root

SYSTEMD_DIRECTORY = $(PACKAGE_ROOT)/usr/lib/systemd/system
CONFIG_DIRECTORY = $(PACKAGE_ROOT)/etc/inventorius_api
NGINX_CONFIG = $(PACKAGE_ROOT)/etc/nginx/conf.d
LIB_DIRECTORY = $(PACKAGE_ROOT)/usr/lib/inventorius-frontend


clean:
	rm -r dist $(PACKAGE_ROOT)

build:
	npm run build:client
	npm run build:server

install:
	sudo dpkg -i dist/inventorius-api_0.3.3_all.deb

deb:
	mkdir -pv $(PACKAGE_ROOT)/DEBIAN
	cp -rv DEBIAN $(PACKAGE_ROOT)
	chmod +x $(PACKAGE_ROOT)/DEBIAN/postinst $(PACKAGE_ROOT)/DEBIAN/prerm

	mkdir -pv $(SYSTEMD_DIRECTORY)
	cp -v systemd/* $(SYSTEMD_DIRECTORY)

	mkdir -pv $(CONFIG_DIRECTORY)
	cp -v config/inventorius.conf $(CONFIG_DIRECTORY)

	mkdir -pv $(NGINX_CONFIG)
	cp -v $(wildcard config/pkg_*.conf) $(NGINX_CONFIG)

	mkdir -pv $(LIB_DIRECTORY)
	cp -vr $(wildcard dist/*) $(LIB_DIRECTORY)

	dpkg-deb --build $(PACKAGE_ROOT)/ dist
