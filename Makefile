PACKER ?= packer
TEMPLATE ?= .

GIT_COMMIT_REF := $(shell git rev-parse --short HEAD 2>/dev/null || echo "unknown")
OUTDIR ?= build
TESTDIR ?= test
BUILDFLAGS = -color=false -on-error=abort

PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ANSIBLE_REPO = "https://github.com/binarycodes/homelab-self-provisioner.git"
ANSIBLE_REPO_PATH = "$(PROJECT_ROOT)/tmp_ansible_checkout"

ACCELERATOR = none
COMMONVARS = -var ansible_repo_path=$(ANSIBLE_REPO_PATH) -var git_commit_ref=$(GIT_COMMIT_REF) -var accelerator=$(ACCELERATOR)

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.ONESHELL:
.PHONY: help init fmt validate build build-kvm clean test ansible-checkout
.SILENT:

help:
	echo "Targets:"
	echo "  make init                  - packer init (plugins, etc.)"
	echo "  make fmt                   - packer format recursively"
	echo "  make validate              - packer validate project"
	echo "  make build                 - packer build without kvm"
	echo "  make build-kvm             - packer build with kvm accelerator"
	echo "  make clean                 - remove output directory"
	echo "  make test                  - test the generated image"
	echo "  make ansible-checkout      - locally checkout the ansible repository"
	echo

init:
	echo "initializing packer project ..."
	$(PACKER) init $(TEMPLATE)

fmt:
	echo "formatting everything recursively ..."
	$(PACKER) fmt -recursive .

validate: clean init fmt ansible-checkout
	echo "running validations ..."
	$(PACKER) validate $(COMMONVARS) $(TEMPLATE)
	find ./scripts -type f -name '*.sh' -print0 | xargs -0r shellcheck

build: clean validate
	echo "builing without kvm ..."
	$(PACKER) build $(BUILDFLAGS) $(COMMONVARS) $(TEMPLATE)

build-kvm: ACCELERATOR:=kvm
build-kvm: clean validate
	echo "building with kvm accelerator ..."
	$(PACKER) build $(BUILDFLAGS) $(COMMONVARS) $(TEMPLATE)

clean:
	echo "cleaning up output directory ..."
	rm -rf --preserve-root=all --one-file-system $(OUTDIR)/

ansible-checkout:
	echo "cloning the ansible repository locally ..."
	rm -rf --preserve-root=all --one-file-system $(ANSIBLE_REPO_PATH)
	git clone --quiet -b main --single-branch "$(ANSIBLE_REPO)" "$(ANSIBLE_REPO_PATH)"

test:
	echo "runnnig tests ..."
	cd $(TESTDIR) && ./start-qemu.sh
