PACKER = packer
TEMPLATE = .

OUTDIR = build
TESTDIR = test
TESTSCRIPT = start-qemu.sh
BUILDFLAGS = -color=false -on-error=ask

.ONESHELL: # Applies to every targets in the file!
.PHONY: help init fmt validate build build-kvm clean test

help:
	@echo "Targets:"
	@echo "  make init                  - packer init (plugins, etc.)"
	@echo "  make fmt                   - packer fmt -recursive ."
	@echo "  make validate              - packer validate TEMPLATE (default: .)"
	@echo "  make build                 - packer build TEMPLATE (default: .)"
	@echo "  make build-kvm             - packer build TEMPLATE (default: .) with kvm accelerator"
	@echo "  make clean                 - remove output directory"
	@echo "  make test                	- test the generated image"
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

test:
	cd $(TESTDIR)
	./$(TESTSCRIPT)
