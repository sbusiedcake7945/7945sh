# 7945sh
Custom fast interactive Linux shell with live syntax highlighting and autocomplete.

## how to compile and package
### step 1: clone the repository
```sh
git clone https://github.com/sbusiedcake7945/7945sh
```
### step 2: go to 7945sh path
```sh
cd 7945sh/
```
### step 3: compile and package
```sh
./package.sh
```
### step 5: install the package
it will create 3 packages choose one that is for your distro we will go with rpm for now
```sh
rpm -ivh ./7945shpkg/7945sh-1.0.0-1.x86_64.rpm
```

> warnings
> if you are on arch linux you could have some problems for that to not happen please compile it your self
> if you run `7945sh` command in your bash session please use `/bin/clear` command to clear after that you can use `clear` until getting back to bash
