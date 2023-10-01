TOPDIR:=$(shell pwd)/topdir
BUILD_DIR := $(shell pwd)/.blddir
SRCROOT := $(shell pwd)
CHROOT_LOCAL_DIR:= $(shell pwd)

NAME:=ilorest
VERSION:=2.4.0
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

export PYTHONPATH=$(BUILD_DIR)/pylib/docutils-0.16:$(BUILD_DIR)/pylib/roman-3.3/src:$(BUILD_DIR)/pylib/Jinja2-2.11.2:$(BUILD_DIR)/pylib/Sphinx-1.0.7
# export http_proxy=proxy.houston.hp.com:8080
tbz:
	rm -rf $(BUILD_DIR)/pylib
	mkdir -p $(BUILD_DIR)/pylib
	tar xfz $(SRCROOT)/packaging/packages/roman/roman-3.3.tar.gz -C $(BUILD_DIR)/pylib
	tar xfz $(SRCROOT)/packaging/packages/sphinx/Sphinx-1.0.7.tar.gz -C $(BUILD_DIR)/pylib
	tar xfz $(SRCROOT)/packaging/packages/docutils/docutils-0.16.tar.gz -C $(BUILD_DIR)/pylib
	tar xfz $(SRCROOT)/packaging/packages/jinja/Jinja2-2.11.2.tar.gz -C $(BUILD_DIR)/pylib

	rm -rf "$(NAME)-$(VERSION)"
	rm -f  "$(NAME)-$(VERSION).tar.bz2"
	mkdir -p "$(NAME)-$(VERSION)"
	tar --exclude=$(NAME)-$(VERSION) \
            --exclude=.svn --exclude=*.pyc --exclude=rdmc-pyinstaller*.spec --exclude=./Makefile -cf - * |\
            ( tar -C $(NAME)-$(VERSION) -xf -)
	sed -e "s/\%VERSION\%/$(VERSION)/g"  -e "s/\%RELEASE\%/$(RELEASE)/g"\
            rdmc.spec.in > "$(NAME)-$(VERSION)/rdmc.spec"
	sed -i -e "s/\%VERSION\%/$(VERSION)/g" -e "s/\%RELEASE\%/$(RELEASE)/g" \
            docs/sphinx/conf.py

	#make -C "$(NAME)-$(VERSION)/docs/sphinx" man  SPHINXBUILD=$(SPHINXBUILD)
	#gzip -c "$(NAME)-$(VERSION)/docs/sphinx/_build/man/ilorest.8" > "$(NAME)-$(VERSION)/docs/sphinx/_build/man/ilorest.8.gz"

	rm -rf "$(NAME)-$(VERSION)/Sphinx-1.0.7"
	rm -rf "$(NAME)-$(VERSION)/docutils-0.16"
	rm -rf "$(NAME)-$(VERSION)/Jinja2-2.11.2"
	rm -rf "$(NAME)-$(VERSION)/scexe_src/scexe.spec"
	cp -r $(MTX_STAGING_PATH)/externals "$(NAME)-$(VERSION)"
	tar cfj "$(NAME)-$(VERSION).tar.bz2" "$(NAME)-$(VERSION)"
	rm -rf "$(NAME)-$(VERSION)"

rpmprep:
	rm -rf $(TOPDIR)
	mkdir -p $(TOPDIR)
	cd $(TOPDIR) && mkdir -p BUILD RPMS SOURCES SPECS SRPMS

rdmc.spec: rdmc.spec.in
	sed -e "s/\%VERSION\%/$(VERSION)/g" -e "s/\%RELEASE\%/$(RELEASE)/g" \
	   $< > $(TOPDIR)/SPECS/$@

rpm: rpmprep tbz rdmc.spec
	cp "$(NAME)-$(VERSION).tar.bz2" $(TOPDIR)/SOURCES/
	rpmbuild -ba --define '_topdir $(TOPDIR)' $(TOPDIR)/SPECS/rdmc.spec

clean:
	rm -f "$(NAME)-$(VERSION).tar.bz2"
	rm -rf topdir .blddir


DEBCHROOTD := $(BUILD_DIR)/chroots/squeeze

rpm-freeze: freeze-src tbz rpms

rpms:
	$(call freeze-chroot,$(MX_ARCH))

	$(CHROOT) $(DEBCHROOTD) bash -c 'useradd -m monkey'
	cp "$(NAME)-$(VERSION).tar.bz2" $(DEBCHROOTD)/home/monkey
	$(CHROOT) $(DEBCHROOTD) bash -c 'su - monkey -c "mkdir -p ~/build && cd ~/build && mkdir -p BUILD RPMS SOURCES SPECS SRPMS"'

	echo "rpmbuild -ta --define '_topdir /home/monkey/build/' /home/monkey/$(NAME)-$(VERSION).tar.bz2 " >> $(DEBCHROOTD)/home/monkey/c.sh
	$(CHROOT) $(DEBCHROOTD) bash -c 'chmod a+x /home/monkey/c.sh'
	$(CHROOT) $(DEBCHROOTD) bash -c 'su - monkey -c "/home/monkey/c.sh"'
	cp -r $(DEBCHROOTD)/home/monkey/build/RPMS/ .

	-find ./RPMS -type f -name '*-debuginfo-*.rpm' -exec rm -f {} \;
	-find ./RPMS -type d -empty -exec rmdir {} \;

ifdef MTX_COLLECTION_PATH
	cp -r ./RPMS $(MTX_COLLECTION_PATH)/
	# hpesign will error out if signing not successful
	hpesign --signonly `find /opt/mxdk/buildagent/work/MTX_COLLECTION_PATH -type f -name '*.rpm'`
endif


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

	# CENTOS/RHEL
	#$(CHROOT) $(DEBCHROOTD) dnf group install -y "Development Tools"
	#$(CHROOT) $(DEBCHROOTD) dnf install -y gcc uuid zlib-devel bzip2 libxml2-devel libxslt-devel ncurses-devel expat-devel sqlite sqlite-devel openssl-devel readline-devel bzip2-devel xz-devel tk-devel libffi-devel
	#$(CHROOT) $(DEBCHROOTD) dnf install -y perl-Text-Template perl-IPC-Cmd perl-Test-Harness perl-Pod-Html perl-Digest-SHA cpan

	# SUSE
	#$(CHROOT) $(DEBCHROOTD) zypper --non-interactive install -t pattern devel_C_C++
	$(CHROOT) $(DEBCHROOTD) zypper --non-interactive install libgcrypt-devel glib2-devel xz-devel tk-devel zlib-devel libxml2-devel libxslt-devel ncurses-devel sqlite3-devel readline-devel libffi-devel openssl bzip2
	#$(CHROOT) $(DEBCHROOTD) zypper --non-interactive install perl-Text-Template perl-IPC-Cmd perl-Test-Harness perl-Pod-Html perl-Digest-SHA cpan

	#tar -xvf $(SRCROOT)/packaging/python3/openssl-3.0.2.tar.gz -C $(DEBCHROOTD)
	tar -xvf $(SRCROOT)/packaging/python3/openssl-1.0.2zf.tar.gz -C $(DEBCHROOTD)
	tar -xvf $(SRCROOT)/packaging/python3/openssl-fips-2.0.16.tar.gz -C $(DEBCHROOTD)

	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /openssl-fips-2.0.16 && ./config && make && make install && cd ..'
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /openssl-1.0.2zf && ./config fips shared --with-fipsdir=/usr/local/ssl/fips-2.0 --prefix=/usr/local/openssl1.0 --openssldir=/usr/local/openssl1.0 -m64 -Wa,--noexecstack threads no-idea no-mdc2 no-rc5 no-krb5 no-ssl2 no-ssl3 enable-asm enable-camellia enable-seed enable-tlsext enable-rfc3779 enable-cms && make depend && make install'
	#$(CHROOT) $(DEBCHROOTD) bash -c 'cd /openssl-openssl-3.0.2 && ./Configure --prefix=/usr/local/openssl3.0 --openssldir=/usr/local/openssl3.0 enable-fips && make && make install'
	echo "/usr/local/openssl1.0/lib" > $(DEBCHROOTD)/etc/ld.so.conf.d/openssl1.0.conf
	#echo "/usr/local/openssl3.0/lib64" > $(DEBCHROOTD)/etc/ld.so.conf.d/openssl3.0.conf
	$(CHROOT) $(DEBCHROOTD) bash -c 'ldconfig'
	$(CHROOT) $(DEBCHROOTD) /usr/local/openssl1.0/bin/openssl version
	#$(CHROOT) $(DEBCHROOTD) /usr/local/openssl3.0/bin/openssl version

	tar xf $(SRCROOT)/packaging/python3/Python-3.8.6.tgz -C $(DEBCHROOTD)
	#tar xf $(SRCROOT)/packaging/python3/Python-3.10.4.tgz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /Python-3.8.6 && ./configure --prefix=/usr/local/python3.8 --enable-shared --with-openssl=/usr/local/openssl1.0/ --with-ssl'
	#$(CHROOT) $(DEBCHROOTD) bash -c 'cd /Python-3.10.4 && ./configure --prefix=/usr/local/python3.10 --enable-shared --with-openssl=/usr/local/openssl3.0/ --with-ssl --enable-optimizations'
	#$(CHROOT) $(DEBCHROOTD) make -C /Python-3.10.4
	#$(CHROOT) $(DEBCHROOTD) make -C /Python-3.10.4 altinstall
	#echo "/usr/local/python3.10/lib" > $(DEBCHROOTD)/etc/ld.so.conf.d/python3.10.conf
	#$(CHROOT) $(DEBCHROOTD) bash -c 'ldconfig'
	#$(CHROOT) $(DEBCHROOTD) bash -c '/usr/local/python3.10/bin/python3.10 --version'
	$(CHROOT) $(DEBCHROOTD) make -C /Python-3.8.6
	$(CHROOT) $(DEBCHROOTD) make -C /Python-3.8.6 install
	echo "/usr/local/python3.8/lib" > $(DEBCHROOTD)/etc/ld.so.conf.d/python3.8.conf
	$(CHROOT) $(DEBCHROOTD) bash -c 'ldconfig'
	$(CHROOT) $(DEBCHROOTD) bash -c '/usr/local/python3.8/bin/python3.8 --version'

	#Added external packages
	$(CHROOT) $(DEBCHROOTD) bash -c '/usr/local/python3.8/bin/python3.8 -m ensurepip --upgrade'

	#Package                   Version
	#------------------------- ---------
	#altgraph                  0.17.2
	#certifi                   2021.10.8
	#colorama                  0.4.4
	#decorator                 5.1.1
	#jsondiff                  1.3.1
	#jsonpatch                 1.32
	#jsonpath-rw               1.4.0
	#jsonpointer               2.2
	#pip                       22.0.4
	#ply                       3.11
	#prompt-toolkit            3.0.29
	#pyaes                     1.6.1
	#pyinstaller               4.10
	#pyinstaller-hooks-contrib 2022.3
	#python-ilorest-library    4.0.0.0
	#pyudev                    0.23.2
	#setuptools                58.1.0
	#tabulate                  0.8.9
	#urllib3                   1.26.9
	#wcwidth                   0.2.5
	#wheel                     0.37.1


	tar xfz $(SRCROOT)/packaging/ext/setuptools-58.1.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /setuptools-58.1.0 && /usr/local/python3.8/bin/python3.8 setup.py install'
	#unzip $(SRCROOT)/packaging/ext/setuptools-58.1.0.zip -d $(DEBCHROOTD)
	#$(CHROOT) $(DEBCHROOTD) bash -c 'cd /setuptools-58.1.0 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/pyinstaller-hooks-contrib-2022.3.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /pyinstaller-hooks-contrib-2022.3 && /usr/local/python3.8/bin/python3.8 setup.py install'
	#tar xfz $(SRCROOT)/packaging/ext/python-dotenv-0.19.2.tar.gz -C $(DEBCHROOTD)
	#$(CHROOT) $(DEBCHROOTD) bash -c 'cd /python-dotenv-0.19.2 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/altgraph-0.17.2.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /altgraph-0.17.2 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/wheel-0.37.1.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /wheel-0.37.1 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/jsonpointer-2.2.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsonpointer-2.2 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/ply-3.11.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /ply-3.11 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/decorator-5.1.1.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /decorator-5.1.1 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/jsonpatch-1.32.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsonpatch-1.32 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/jsonpath-rw-1.4.0.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsonpath-rw-1.4.0 && /usr/local/python3.8/bin/python3.8 setup.py install'
	#tar xfz $(SRCROOT)/packaging/ext/setproctitle-1.2.2.tar.gz -C $(DEBCHROOTD)
	#$(CHROOT) $(DEBCHROOTD) bash -c 'cd /setproctitle-1.2.2 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/pyudev-0.23.2.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /pyudev-0.23.2 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/jsondiff-1.3.1.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /jsondiff-1.3.1 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/pyaes-1.6.1.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /pyaes-1.6.1 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/urllib3-1.26.9.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /urllib3-1.26.9 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/colorama-0.4.4.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'export LC_ALL=en_US.UTF-8 && cd /colorama-0.4.4 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/tabulate-0.8.9.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /tabulate-0.8.9 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/wcwidth-0.2.5.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /wcwidth-0.2.5 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/prompt_toolkit-3.0.29.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /prompt_toolkit-3.0.29 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/certifi-2021.10.8.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /certifi-2021.10.8 && /usr/local/python3.8/bin/python3.8 setup.py install'
	tar xfz $(SRCROOT)/packaging/ext/pyinstaller-4.10.tar.gz -C $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /pyinstaller-4.10/bootloader && /usr/local/python3.8/bin/python3.8 ./waf distclean all && cd .. && /usr/local/python3.8/bin/python3.8 setup.py install'
	cp -r $(MTX_STAGING_PATH)/externals/*.zip packaging/ext
	unzip packaging/ext/python-ilorest-library-$(MX_ILOREST_LIB_VERSION).zip -d $(DEBCHROOTD)
	$(CHROOT) $(DEBCHROOTD) bash -c 'cd /python-ilorest-library-$(MX_ILOREST_LIB_VERSION) && /usr/local/python3.8/bin/python3.8 setup.py install'
	$(CHROOT) $(DEBCHROOTD) bash -c '/usr/local/python3.8/bin/pip3.8 list'
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
