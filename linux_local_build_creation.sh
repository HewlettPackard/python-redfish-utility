#!/bin/bash

# Variables
current_dir=$(pwd)
NAME="ilorest"
VERSION="6.1.0.0"
RELEASE="1"
PACKAGE="$NAME-$VERSION"
TARBALL="$PACKAGE.tar.bz2"
SPEC_FILE="rdmc.spec10local.in"
USER="monkey"
USER_HOME="/home/$USER"

# Output the product name
echo "Product: $NAME-$VERSION-$RELEASE"

# Create the build directory and prepare the source
echo "Preparing source directory..."
mkdir -p "$PACKAGE"
tar --exclude="$PACKAGE" --exclude=".svn" --exclude="*.pyc" --exclude="rdmc-pyinstaller*.spec" --exclude="./Makefile" -cf - * | tar -C "$PACKAGE" -xf -

# Modify the spec file
echo "Modifying spec file..."
sed -e "s/%VERSION%/${VERSION}/g" -e "s/%NAME%/$NAME/g" -e "s/%RELEASE%/$RELEASE/g" "$SPEC_FILE" > "$PACKAGE/rdmc.spec"

# Copy external files and create the tarball
echo "Creating tarball..."
cp -r /home/MTX_STAGING_PATH/externals "$PACKAGE"
tar cfj "$TARBALL" "$PACKAGE"

# Prepare the script to be run by the user
echo "Preparing user script..."
chmod +x "$USER_HOME/c.sh"
rm -f "$USER_HOME/c.sh"
echo "rpmbuild -ta --define '_topdir $USER_HOME/build/' $USER_HOME/$TARBALL" >> "$USER_HOME/c.sh"
chmod a+x "$USER_HOME/c.sh"

# Add user and copy tarball
# Uncomment the following line if the user doesn't exist and needs to be added
# id -u $USER &>/dev/null || sudo useradd -m $USER

echo "Copying tarball to user's home directory..."
cp "$TARBALL" "$USER_HOME"

# Run the script as the specified user
echo "Running script as $USER..."
su - "$USER" -c "$USER_HOME/c.sh"
