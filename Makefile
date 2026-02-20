WORKDIR := "./workspace"
PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ALLOWED_OS_ROLE := debian-base debian-container debian-kubernetes

empty :=
space := $(empty) $(empty)
TOKENS = $(subst -, ,$@)
OS = $(word 1,$(TOKENS))
ROLE = $(word 2,$(TOKENS))
ACTION_TOKENS = $(wordlist 3,$(words $(TOKENS)),$(TOKENS))
ACTION = $(subst $(space),-,$(strip $(ACTION_TOKENS)))

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.ONESHELL:
.PHONY: help clean ansible-checkout deb-base
.SILENT:


help:
	echo "Available OS-ROLE combinations are $(ALLOWED_OS_ROLE)"
	echo
	echo "Targets:"
	echo "  make *-fmt                   - packer format recursively"
	echo "  make *-validate              - packer validate project"
	echo "  make *-build                 - packer build without kvm"
	echo "  make *-build-kvm             - packer build with kvm accelerator"
	echo "  make *-test                  - test the generated image"
	echo

%-fmt %-validate %-build %-build-kvm %-test: clean
	echo "preparing workspace for: os - $(OS), role - $(ROLE), action - $(ACTION) ..."

	if ! echo " $(ALLOWED_OS_ROLE) " | grep -q " $(OS)-$(ROLE) "; then
	  echo "error: unsupported os-role '$(OS)-$(ROLE)' in target '$@'"
	  exit 2
	fi

	cd $(WORKDIR)
	ln -snf $(PROJECT_ROOT)/common/$(OS)/images/$(ROLE)/* ./
	ln -snf $(PROJECT_ROOT)/common/$(OS)/shared/packer/* ./
	ln -snf $(PROJECT_ROOT)/common/$(OS)/shared/vars/* ./
	ln -snf $(PROJECT_ROOT)/common/$(OS)/shared/scripts ./
	ln -snf $(PROJECT_ROOT)/common/Makefile ./
	ln -snf $(PROJECT_ROOT)/common/*.hcl ./
	ln -snf $(PROJECT_ROOT)/common/cloud-init ./
	ln -snf $(PROJECT_ROOT)/common/$(OS)/test ./

	$(MAKE) --no-print-directory $(ACTION) TEST_IMAGE_NAME=$(OS)-$(ROLE)

clean:
	rm -rf --preserve-root=all --one-file-system "$(PROJECT_ROOT)/$(WORKDIR)"
	mkdir "$(PROJECT_ROOT)/$(WORKDIR)"
