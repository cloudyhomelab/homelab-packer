PACKER ?= packer
TEMPLATE ?= .

GIT_COMMIT_REF := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
OUTDIR ?= build
TESTDIR ?= test
BUILDFLAGS = -color=false -on-error=abort

ACCELERATOR = none
COMMONVARS = -var git_commit_ref=$(GIT_COMMIT_REF) -var accelerator=$(ACCELERATOR)

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.ONESHELL:
.PHONY: help init fmt validate build build-kvm clean test

help:
	@echo "Targets:"
	@echo "  make init                  - packer init (plugins, etc.)"
	@echo "  make fmt                   - packer fmt -recursive ."
	@echo "  make validate              - packer validate TEMPLATE (default: .)"
	@echo "  make build                 - packer build TEMPLATE (default: .)"
	@echo "  make build-kvm             - packer build TEMPLATE (default: .) with kvm accelerator"
	@echo "  make clean                 - remove output directory"
	@echo "  make test                  - test the generated image"
	@echo

init:
	$(PACKER) init $(TEMPLATE)

fmt:
	$(PACKER) fmt -recursive .

validate: init fmt
	$(PACKER) validate $(COMMONVARS) $(TEMPLATE)
	find ./scripts -type f -name '*.sh' -print0 | xargs -0r shellcheck

build: clean validate
	$(PACKER) build $(BUILDFLAGS) $(COMMONVARS) $(TEMPLATE)

build-kvm: ACCELERATOR:=kvm
build-kvm: clean validate
	$(PACKER) build $(BUILDFLAGS) $(COMMONVARS) $(TEMPLATE)

clean:
	rm -rf $(OUTDIR)/

test:
	cd $(TESTDIR) && ./start-qemu.sh
