# 7945sh
Custom fast interactive Linux shell with live syntax highlighting and autocomplete.

## dependencies
```sh
pip install prompt_toolkit pyinstaller
```

## how to compile and package
### step 1: clone the repository
```sh
git clone https://github.com/busiedcake7945/7945sh
```
### step 2: go to 7945sh path
```sh
cd 7945sh/
```
### step 3: compiile
```sh
pyinstaller --onefile 7945sh.py
```
### step 4: package
```sh
./package.sh
```
### step 5: install the package
it will create 3 packages choose one that is for your distro we will go with rpm for now
```sh
rpm -ivh ./7945shpkg/7945sh-1.0.0-1.x86_64.rpm
```