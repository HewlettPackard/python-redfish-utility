BUILD_DIR := $(PWD)/dist/rpmbuild
SRCROOT := $(shell pwd)
CHROOT_LOCAL_DIR:= $(shell pwd)
BUILD_METADATA ?= 1~development~$(shell git rev-parse --short HEAD)

NAME:=ilorest
VERSION := $(shell awk '/Version/{print $$NF; exit}' ${SRCROOT}/docs/slate/source/includes/_changelog.md)
RELEASE:=1
SPHINXBUILD:=$(BUILD_DIR)/pylib/Sphinx-1.0.7/sphinx-build.py
BLOFLY := /net
#CREATE_CHROOT := /net/blofly.us.rdlabs.hpecorp.net/data/blofly/iss-linux-sdk/chrootbuilder/create_chroot.sh
CREATE_CHROOT := $(CHROOT_LOCAL_DIR)/chrootbuilder/create_chroot.sh
#CHROOT := /net/blofly.us.rdlabs.hpecorp.net/data/blofly/iss-linux-sdk/chrootbuilder/tools/muchroot
CHROOT := $(CHROOT_LOCAL_DIR)/chrootbuilder/tools/muchroot
UNAME_SPOOF := /net/blofly.us.rdlabs.hpecorp.net/data/blofly/iss-linux-sdk/chrootbuilder/tools/uname_spoof
export CHROOT_DESTDIR=/home

ifdef MTX_PRODUCT_VERSION
  VERSION:=$(MTX_PRODUCT_VERSION)
endif

ifdef MTX_BUILD_NUMBER
  RELEASE:=$(MTX_BUILD_NUMBER)
endif

all: rpm

chif:
	mkdir -pv ./externals
	curl -O https://downloads.hpe.com/pub/softlib2/software1/pubsw-linux/p1093353304/v168967/ilorest_chif.so
	mv ilorest_chif.so externals

rpmprep:
	mkdir -p $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/BUILD $(BUILD_DIR)/RPMS $(BUILD_DIR)/SOURCES $(BUILD_DIR)/SPECS $(BUILD_DIR)/SRPMS

doc-ver:
	sed -e "s/^version =.*/version = '$(VERSION)'/" -e "s/^release =.*/release = '$(VERSION)-$(RELEASE)'/" \
 		< docs/sphinx/conf.py > docs/sphinx/conf.py.new
	mv docs/sphinx/conf.py.new docs/sphinx/conf.py
 
rdmc.spec: rdmc.spec.in
	sed -e "s/\%VERSION\%/$(VERSION)/g" -e "s/\%RELEASE\%/$(RELEASE)/g" \
	   $< > $@
	cp -pv $@ $(BUILD_DIR)/SPECS/$@

rpm: doc-ver rpmprep rdmc.spec
	tar --transform 'flags=r;s,^,/${NAME}-${VERSION}/,' --exclude .git --exclude .gitignore --exclude dist -cvjf ${BUILD_DIR}/SOURCES/${NAME}-${VERSION}.tar.bz2 .
	BUILD_METADATA=$(BUILD_METADATA) rpmbuild -ts ${BUILD_DIR}/SOURCES/${NAME}-${VERSION}.tar.bz2 --define "_topdir $(BUILD_DIR)"
	BUILD_METADATA=$(BUILD_METADATA) rpmbuild -ba rdmc.spec --define "_topdir $(BUILD_DIR)"

clean:
	rm -f "$(NAME)-$(VERSION).tar.bz2"
	rm -rf $(BUILD_DIR)

DEBCHROOTD := $(BUILD_DIR)/chroots/squeeze

freeze-src:
	rm -rf hp
	git clone git@github.hpe.com:ess-morpheus/chrootbuilder.git $(CHROOT_LOCAL_DIR)/chrootbuilder

define freeze-bin
	$(call freeze-src,$1)
	$(CHROOT) $1 bash -c 'cd /$(NAME)-$(VERSION) && /opt/python3.8/bin/python3.8 setup.py build'
	bash ./scexe_src/scexe -o $(NAME) -i $(NAME) $1/$(NAME)-$(VERSION)/build/exe.linux-x86_64*/*
endef

define freeze-chroot
	rm -rf $(BUILD_DIR)/chroots
	# create the chroot

	$(CREATE_CHROOT) -d SLES12SP2 -a $1 -D $(DEBCHROOTD)

	#import keys
	cp -r $(CHROOT_LOCAL_DIR)/chrootbuilder/public_keys $(DEBCHROOTD)/
	$(CHROOT) $(DEBCHROOTD) mkdir -p /usr/lib/rpm/gnupg/
	#$(CHROOT) $(DEBCHROOTD) bash -c 'gpg --import /public_keys/*.asc'

	$(CHROOT) $(DEBCHROOTD) zypper --non-interactive install zlib-devel libffi-devel openssl
	$(CHROOT) $(DEBCHROOTD) zypper --non-interactive install libxml2-devel libxslt-devel ncurses-devel expat sqlite3-devel readline-devel bzip2
	$(CHROOT) $(DEBCHROOTD) openssl version
	$(CHROOT) $(DEBCHROOTD) bash -c 'export LC_ALL=en_US.UTF-8'
	$(CHROOT) $(DEBCHROOTD) bash -c 'export PYTHONIOENCODING=UTF-8'

	tar -xvf $(SRCROOT)/packaging/python3/openssl-1.0.2y.tar.gz -C $(DEBCHROOTD)
	tar -xvf $(SRCROOT)/packaging/python3/openssl-fips-2.0.16.tar.gz -C $(DEBCHROOTD)

	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /openssl-fips-2.0.16 && ./config && make && make install && cd ..'
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /openssl-1.0.2y && ./config fips shared --with-fipsdir=/usr/local/ssl/fips-2.0 -m64 -Wa,--noexecstack threads no-idea no-mdc2 no-rc5 no-krb5 no-ssl2 no-ssl3 enable-asm enable-camellia enable-seed enable-tlsext enable-rfc3779 enable-cms && make depend && make install'
	$(CHROOT) $(DEBCHROOTD) /usr/local/ssl/bin/./openssl version

	$(CHROOT) $(DEBCHROOTD) ln -s -f /usr/local/ssl/bin/openssl /usr/bin/openssl
	$(CHROOT) $(DEBCHROOTD) openssl version

	#$(CHROOT) $(DEBCHROOTD) mv /usr/lib64/libcrypto.so.1.1 /usr/lib64/old_libcrypto.so.1.1
	#$(CHROOT) $(DEBCHROOTD) mv /usr/lib64/libssl.so.1.1 /usr/lib64/old_libssl.so.1.1

	$(CHROOT) $(DEBCHROOTD) cp /usr/local/ssl/lib/libcrypto.so.1.0.0 /usr/lib64/ && \
	$(CHROOT) $(DEBCHROOTD) cp /usr/local/ssl/lib/libssl.so.1.0.0 /usr/lib64/

	tar xf $(SRCROOT)/packaging/python3/Python-3.8.6.tgz -C $(DEBCHROOTD)

	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /Python-3.8.6 && ./configure --prefix=/usr/local/python3.8 --enable-shared --with-openssl=/usr/local/ssl/'

	$(CHROOT) $(DEBCHROOTD) make -C /Python-3.8.6
	$(CHROOT) $(DEBCHROOTD) make -C /Python-3.8.6 install

	$(CHROOT) $(DEBCHROOTD) cp /usr/local/python3.8/lib/libpython3.8.so.1.0 /usr/lib64/
	$(CHROOT) $(DEBCHROOTD) cp /usr/local/python3.8/lib/libpython3.8.so.1.0 /lib64/

	#Added external packages
	$(CHROOT) $(DEBCHROOTD) bash -c '/usr/local/python3.8/bin/python3.8 -m ensurepip --upgrade'

	tar xfz $(SRCROOT)/packaging/ext/setuptools-59.1.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /setuptools-59.1.0 && /usr/local/python3.8/bin/python3.8 setup.py install'
	#unzip $(SRCROOT)/packaging/ext/setuptools-59.1.0.zip -d $(DEBCHROOTD)
	#$(CHROOT) $(DEBCHROOTD) bash -c 'cd /setuptools-50.3.2 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/pyinstaller-hooks-contrib-2021.3.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /pyinstaller-hooks-contrib-2021.3 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/python-dotenv-0.19.2.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /python-dotenv-0.19.2 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/altgraph-0.17.2.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /altgraph-0.17.2 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/pyinstaller/PyInstaller-3.6.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /PyInstaller-3.6 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/jsonpointer-2.2.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsonpointer-2.2 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/six-1.16.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /six-1.16.0 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/ply-3.11.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /ply-3.11 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/decorator-5.1.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /decorator-5.1.0 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/jsonpatch-1.32.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsonpatch-1.32 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/jsonpath-rw-1.4.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsonpath-rw-1.4.0 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/setproctitle-1.2.2.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /setproctitle-1.2.2 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/pyudev-0.22.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /pyudev-0.22.0 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/jsondiff-1.3.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsondiff-1.3.0 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/pyaes-1.6.1.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /pyaes-1.6.1 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/urllib3-1.26.7.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /urllib3-1.26.7 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/colorama-0.4.4.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'export LC_ALL=en_US.UTF-8 && cd /colorama-0.4.4 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/tabulate-0.8.9.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /tabulate-0.8.9 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/wcwidth-0.2.5.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /wcwidth-0.2.5 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/prompt_toolkit-2.0.10.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /prompt_toolkit-2.0.10 && /usr/local/python3.8/bin/python3.8 setup.py install'

	tar xfz $(SRCROOT)/packaging/ext/certifi-2021.10.8.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /certifi-2021.10.8 && /usr/local/python3.8/bin/python3.8 setup.py install'

	cp -r $(MTX_STAGING_PATH)/externals/*.zip packaging/ext
	unzip packaging/ext/python-ilorest-library-$(MX_ILOREST_LIB_VERSION).zip -d $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /python-ilorest-library-$(MX_ILOREST_LIB_VERSION) && /usr/local/python3.8/bin/python3.8 setup.py install'
endef

freeze: freeze-x86_64

freeze-x86_64: export OPENSSL_ROOT=/usr/local/ssl/
freeze-x86_64:
	$(call freeze-chroot,x86_64)
	$(call freeze-bin,$(DEBCHROOTD))

ifdef MTX_COLLECTION_PATH
	mkdir -p ${MTX_COLLECTION_PATH}/x86_64
	mv ./$(NAME) ${MTX_COLLECTION_PATH}/x86_64
endif

freeze-i386:
	$(call freeze-chroot,i386)
	$(call freeze-bin,$(DEBCHROOTD),i386)

ifdef MTX_COLLECTION_PATH
	mkdir -p ${MTX_COLLECTION_PATH}/i386
	mv ./$(NAME) ${MTX_COLLECTION_PATH}/i386
endif

deb:
	sudo apt-get -y install alien
	sudo alien $(MTX_STAGING_PATH)/rpmlocation/RPMS/x86_64/*.rpm
	mkdir temp
	dpkg-deb -R *.deb temp
	mv temp/usr/lib64 temp/usr/lib
	mkdir temp/usr/lib/x86_64-linux-gnu
	cp temp/usr/lib/ilorest_chif.so temp/usr/lib/x86_64-linux-gnu/
	rm temp/usr/lib/ilorest_chif.so
	dpkg-deb -b temp new.deb
	rm ilorest*.deb
	mv new.deb $(NAME)-$(VERSION)-$(RELEASE)_amd64.deb
	mkdir -p DEB && cp *.deb DEB
	cp -r DEB $(MTX_COLLECTION_PATH)/

