PACKER = packer
TEMPLATE = .

OUTDIR = build
TESTDIR = test
TESTSCRIPT = start-qemu.sh
BUILDFLAGS = -color=false -on-error=ask

.ONESHELL: # Applies to every targets in the file!
.PHONY: help init fmt validate build build-kvm clean test

define POST_BUILD_TASK
	image_name=$$(jq -r ".builds[0].files[0].name" $(OUTDIR)/packer-manifest.json)
	sed -i "s/DOWNLOAD_FILE_NAME=.*/DOWNLOAD_FILE_NAME=\"$$image_name\"/" $(TESTDIR)/$(TESTSCRIPT)
endef

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
	$(POST_BUILD_TASK)

build-kvm: validate
	$(PACKER) build $(BUILDFLAGS) -var accelerator=kvm $(TEMPLATE)
	$(POST_BUILD_TASK)

clean:
	rm -rf $(OUTDIR)/

test:
	cd $(TESTDIR)
	./$(TESTSCRIPT)
