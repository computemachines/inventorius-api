.PHONY: deb clean build install test-solver

PACKAGE_ROOT = ./package-root

PYTHON_DIST_PACKAGES = $(PACKAGE_ROOT)/usr/lib/python3/dist-packages/
SYSTEMD_DIRECTORY = $(PACKAGE_ROOT)/usr/lib/systemd/system
CONFIG_DIRECTORY = $(PACKAGE_ROOT)/etc/inventorius
UWSGI_APPS_AVAILABLE = $(PACKAGE_ROOT)/etc/uwsgi/apps-available/
UWSGI_APPS_ENABLED = $(PACKAGE_ROOT)/etc/uwsgi/apps-enabled/

SOLVER_TESTS = \
	tests/test_quantity_constraints.py \
	tests/test_process_quantities.py \
	tests/test_provenance.py \
	tests/test_provenance_serialization.py \
	tests/solver

# Keep this lane independent of the repository conftest, whose fixtures require
# MongoDB.  The solver laboratory must stay runnable from a clean checkout with
# only the project's normal Python dependencies installed.
test-solver:
	PYTHONPATH=src uv run --with-requirements requirements.txt \
		pytest --confcutdir=tests/solver $(SOLVER_TESTS)

clean:
	rm -rv dist/*
	rm -r $(PACKAGE_ROOT)/

build:
	python -m build

install:
	sudo dpkg -i dist/inventorius-api_0.3.11_all.deb

deb:
	mkdir -pv $(PACKAGE_ROOT)/DEBIAN
	cp -rv DEBIAN $(PACKAGE_ROOT)
	chmod +x $(PACKAGE_ROOT)/DEBIAN/postinst $(PACKAGE_ROOT)/DEBIAN/prerm

	mkdir -pv $(SYSTEMD_DIRECTORY)
	cp -v systemd/* $(SYSTEMD_DIRECTORY)

	mkdir -pv $(PYTHON_DIST_PACKAGES)
	pip install --target $(PYTHON_DIST_PACKAGES) $(wildcard dist/inventorius_api-*-none-any.whl)

	mkdir -pv $(UWSGI_APPS_AVAILABLE)
	cp -v config/pkg_inventorius-api.ini $(UWSGI_APPS_AVAILABLE)
	mkdir -pv $(UWSGI_APPS_ENABLED)

	dpkg-deb --build $(PACKAGE_ROOT)/ dist
