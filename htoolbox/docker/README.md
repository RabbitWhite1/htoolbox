# HToolBox - Docker

## Build

```sh
docker build \
  --build-arg UID=$(id -u) \
  --build-arg GID=$(id -g) \
  --build-arg UNAME=$(id -un) \
  --build-arg GNAME=$(id -gn) \
  -t hankzhwang/htoolbox:latest .
```

## Run

```sh
docker run -it hankzhwang/htoolbox /bin/bash
```
