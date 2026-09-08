PYTHON ?= python3
OUT ?= dist/build
RELEASE_OUT ?= dist/release
LAB_VARIANT ?= v7235
CASES ?= repeat

.PHONY: check test build installer release test-lab

check:
	$(PYTHON) -m tools.check
	$(MAKE) test

test:
	$(PYTHON) -m unittest discover -s tests/unit -v

build:
	$(PYTHON) -m tools.image --build --output "$(OUT)"

installer:
	$(PYTHON) -m tools.installer

release:
	$(PYTHON) -m tools.release --version "$(VERSION)" --bundle "$(OUT)" --output "$(RELEASE_OUT)"

test-lab:
	MIKROWARP_LAB_VARIANT=$(LAB_VARIANT) $(PYTHON) -m tests.lab.acceptance $(CASES)
