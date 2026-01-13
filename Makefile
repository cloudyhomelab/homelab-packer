PACKER = packer
TEMPLATE = .

OUTDIR = build

BUILDFLAGS = -color=false -on-error=ask
IMAGEPATH = $(OUTDIR)/$(IMAGENAME).$(IMAGEFORMAT)

.PHONY: help init fmt validate build build-kvm clean

help:
	@echo "Targets:"
	@echo "  make init                  - packer init (plugins, etc.)"
	@echo "  make fmt                   - packer fmt -recursive ."
	@echo "  make validate              - packer validate TEMPLATE (default: .)"
	@echo "  make build                 - packer build TEMPLATE (default: .)"
	@echo "  make build-kvm             - packer build TEMPLATE (default: .) with kvm accelerator"
	@echo "  make clean                 - remove output directory"
	@echo

init: clean
	$(PACKER) init $(TEMPLATE)

fmt: init
	$(PACKER) fmt -recursive .

validate: init fmt
	$(PACKER) validate $(TEMPLATE)

build: validate
	$(PACKER) build $(BUILDFLAGS) $(TEMPLATE)

build-kvm: validate
	$(PACKER) build $(BUILDFLAGS) -var accelerator=kvm $(TEMPLATE)

clean:
	rm -rf $(OUTDIR)/
