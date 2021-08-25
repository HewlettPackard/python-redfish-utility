NAME ?= ilorest
VERSION ?= $(shell cat .version)
# FIXME: When does this switch to release or when it is omitted?
BUILD_METADATA ?= 1~development~$(shell git rev-parse --short HEAD)

SPEC_FILE ?= ${NAME}.spec
SOURCE_NAME ?= ${NAME}
BUILD_DIR ?= $(PWD)/dist/rpmbuild
SOURCE_PATH := ${BUILD_DIR}/SOURCES/${SOURCE_NAME}-${VERSION}.tar.bz2

rpm: rpm_package_source rpm_build_source rpm_build

prepare:
	sed -e "s/\%VERSION\%/$(VERSION)/g"  -e 's/%RELEASE%/'"${BUILD_METADATA}"'/g' ${NAME}.spec.in > ${NAME}.spec
	sed -i -e "s/\%VERSION\%/$(VERSION)/g" -e 's/%RELEASE%/'"${BUILD_METADATA}"'/g' docs/sphinx/conf.py
	cat ${NAME}.spec
	rm -rf $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/SPECS $(BUILD_DIR)/SOURCES
	cp $(SPEC_FILE) $(BUILD_DIR)/SPECS/

rpm_package_source:
	tar --transform 'flags=r;s,^,/${NAME}-${VERSION}/,' --exclude .git --exclude dist -cvjf $(SOURCE_PATH) .

rpm_build_source:
	BUILD_METADATA=$(BUILD_METADATA) rpmbuild -ts $(SOURCE_PATH) --define "_topdir $(BUILD_DIR)"

rpm_build:
	BUILD_METADATA=$(BUILD_METADATA) rpmbuild -ba $(SPEC_FILE) --define "_topdir $(BUILD_DIR)"
