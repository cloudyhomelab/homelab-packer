PACKER ?= packer
TEMPLATE ?= .
OUTDIR = build
IMAGENAME = debian-custom-trixie
IMAGEFORMAT = qcow2
BUILDFLAGS = -var output_directory=$(OUTDIR) -var image_name=$(IMAGENAME) -var image_format=$(IMAGEFORMAT) -color=false
IMAGEPATH = $(OUTDIR)/$(IMAGENAME).$(IMAGEFORMAT)
ANSIBLE_REPOPATH = tmp_ansible_checkout
ANSIBLE_REPO = https://github.com/binarycodes/homelab-self-provisioner.git
ANSIBLE_REPOBRANCH = main

.PHONY: help init fmt validate build clean docker qemu

help:
	@echo "Targets:"
	@echo "  make init                  - packer init (plugins, etc.)"
	@echo "  make fmt                   - packer fmt -recursive ."
	@echo "  make validate              - packer validate TEMPLATE (default: .)"
	@echo "  make build                 - packer build TEMPLATE (default: .)"
	@echo "  make build-kvm             - packer build TEMPLATE (default: .) with kvm accelerator"
	@echo "  make check                 - check generated image"
	@echo "  make clean                 - remove output directory"
	@echo
	@echo "Vars:"
	@echo "  TEMPLATE=path/to/file.pkr.hcl or dir (default: .)"

init: clean
	$(PACKER) init $(TEMPLATE)
	git clone -b $(ANSIBLE_REPOBRANCH) --single-branch $(ANSIBLE_REPO) $(ANSIBLE_REPOPATH)

fmt: init
	$(PACKER) fmt -recursive .

validate: init fmt
	$(PACKER) validate $(TEMPLATE)

build: validate
	$(PACKER) build $(BUILDFLAGS) $(TEMPLATE)
	qemu-img check $(IMAGEPATH)

build-kvm: validate
	$(PACKER) build $(BUILDFLAGS) -var accelerator=kvm $(TEMPLATE)
	qemu-img check $(IMAGEPATH)

check:
	qemu-img check $(IMAGEPATH)

clean:
	rm -rf $(OUTDIR)/
	rm -rf $(ANSIBLE_REPOPATH)
