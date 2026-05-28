#!/bin/bash
set -e
trap 'echo "ERROR: Script failed at line $LINENO"' ERR

CWD=$(dirname "$(realpath "$0")")
VERSION="1.0.0"
BUILD_DIR="$CWD/build_packages"
OUT_DIR="$CWD/7945shpkg"

echo "=== Cleaning previous packaging build directories ==="
rm -rf "$BUILD_DIR"
rm -rf "$OUT_DIR"
mkdir -p "$BUILD_DIR"
mkdir -p "$OUT_DIR"

# Clean old packages at root
rm -f "$CWD"/7945sh_${VERSION}_amd64.deb "$CWD"/7945sh-${VERSION}-1-x86_64.pkg.tar.zst "$CWD"/7945sh-${VERSION}-1.x86_64.rpm

# Step 1: Ensure up-to-date shell binary
echo "=== Building shell executable binary ==="
python3 -m PyInstaller --onefile --name 7945sh "$CWD/7945sh.py"
rm -f "$CWD/7945sh"
cp "$CWD/dist/7945sh" "$CWD/7945sh"

# Create staging structure for 7945sh only
ROOT_DIR="$BUILD_DIR/root"
mkdir -p "$ROOT_DIR/usr/bin"
cp "$CWD/7945sh" "$ROOT_DIR/usr/bin/7945sh"

# ----------------- DEBIAN PACKAGE -----------------
echo "=== Packaging DEB (.deb) ==="
DEB_STAGE="$BUILD_DIR/deb"
mkdir -p "$DEB_STAGE/DEBIAN"
cp -r "$ROOT_DIR/usr" "$DEB_STAGE/"

cat << EOF > "$DEB_STAGE/DEBIAN/control"
Package: 7945sh
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: busiedcake7945 <busiedcake7945@7945pc>
Description: Custom fast interactive Linux shell with live syntax highlighting and autocomplete.
EOF

# Build DEB manually using tar and ar
cd "$DEB_STAGE/DEBIAN"
tar -czf "$BUILD_DIR/control.tar.gz" control
cd "$DEB_STAGE"
tar -cJf "$BUILD_DIR/data.tar.xz" usr
echo "2.0" > "$BUILD_DIR/debian-binary"

cd "$BUILD_DIR"
ar rcs "$OUT_DIR/7945sh_${VERSION}_amd64.deb" debian-binary control.tar.gz data.tar.xz
echo "-> DEB Package built successfully at 7945shpkg/7945sh_${VERSION}_amd64.deb"

# ----------------- ARCH LINUX PACKAGE -----------------
echo "=== Packaging Arch Linux (.pkg.tar.zst) ==="
ARCH_STAGE="$BUILD_DIR/arch"
mkdir -p "$ARCH_STAGE"
cp -r "$ROOT_DIR/usr" "$ARCH_STAGE/"

cat << EOF > "$ARCH_STAGE/.PKGINFO"
pkgname = 7945sh
pkgver = $VERSION-1
pkgdesc = Custom fast interactive Linux shell with live syntax highlighting and autocomplete
url = https://github.com/busiedcake7945/terminal
arch = x86_64
license = MIT
EOF

cd "$ARCH_STAGE"
tar -I 'zstd' -cf "$OUT_DIR/7945sh-${VERSION}-1-x86_64.pkg.tar.zst" .PKGINFO usr
echo "-> Arch Package built successfully at 7945shpkg/7945sh-${VERSION}-1-x86_64.pkg.tar.zst"

# ----------------- RPM PACKAGE -----------------
echo "=== Packaging RPM (.rpm) ==="
RPM_TOP="$BUILD_DIR/rpmbuild"
mkdir -p "$RPM_TOP"/{SPECS,SOURCES,BUILD,RPMS,SRPMS}

cp "$CWD/7945sh" "$RPM_TOP/SOURCES/"

cat << EOF > "$RPM_TOP/SPECS/7945sh.spec"
Name:           7945sh
Version:        $VERSION
Release:        1%{?dist}
Summary:        Custom fast interactive Linux shell with live syntax highlighting and autocomplete

License:        MIT
URL:            https://github.com/busiedcake7945/terminal

# Disable debuginfo package
%define debug_package %{nil}

%description
Custom fast interactive Linux shell with live syntax highlighting and autocomplete.

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}/usr/bin

cp %{_sourcedir}/7945sh %{buildroot}/usr/bin/7945sh

%files
/usr/bin/7945sh

%changelog
* Wed May 27 2026 busiedcake7945 <busiedcake7945@7945pc> - 1.0.0-1
- Initial release
EOF

rpmbuild --define "_topdir $RPM_TOP" -bb "$RPM_TOP/SPECS/7945sh.spec"
cp "$RPM_TOP"/RPMS/x86_64/7945sh-1.0.0-1.*.rpm "$OUT_DIR/7945sh-${VERSION}-1.x86_64.rpm"
echo "-> RPM Package built successfully at 7945shpkg/7945sh-${VERSION}-1.x86_64.rpm"

# Clean up temp builds
rm -rf "$BUILD_DIR"
echo "=== ALL 7945SH PACKAGES COMPLETED SUCCESSFULLY ==="
