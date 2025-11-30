PACKER ?= packer
TEMPLATE ?= .
OUTDIR = build

.PHONY: help init fmt validate build clean docker qemu

help:
	@echo "Targets:"
	@echo "  make init                  - packer init (plugins, etc.)"
	@echo "  make fmt                   - packer fmt -recursive ."
	@echo "  make validate              - packer validate TEMPLATE (default: .)"
	@echo "  make build                 - packer build TEMPLATE (default: .)"
	@echo "  make build-kvm             - packer build TEMPLATE (default: .) with kvm accelerator"
	@echo "  make clean                 - remove output directory"
	@echo
	@echo "Vars:"
	@echo "  TEMPLATE=path/to/file.pkr.hcl or dir (default: .)"

init:
	$(PACKER) init $(TEMPLATE)

fmt: init
	$(PACKER) fmt -recursive .

validate: init fmt clean
	$(PACKER) validate $(TEMPLATE)

build: validate
	$(PACKER) build $(TEMPLATE)

build-kvm: validate
	$(PACKER) build -var accelerator=kvm $(TEMPLATE)

clean:
	rm -rf $(OUTDIR)/
