# Docker Compose

## Prerequisites

- [Docker Engine](https://docs.docker.com/engine/install/): version 1.13.0 or newer
- [Docker Compose](https://docs.docker.com/compose/install/): version 1.10.0 or newer

## Setting up env variable

### Update the .env file with appropriate values in placeholder

```console
REACT_APP_API_DOMAIN= 'http://localhost:3001/api/'

# MYSQL PARAMS
MYSQL_DATABASE= "<MYSQL_DATABASE>"
MYSQL_USER= "<MYSQL_USER>"
MYSQ_PASSWORD= "<MYSQL_ROOT_PASSWORD>"
MYSQL_ROOT_PASSWORD= "<MYSQL_ROOT_PASSWORD>"
MYSQL_WRITER_HOST= "<DB service name in docker-compose.yaml>"
DJANGO_SUPERUSER_USERNAME= "<DJANGO_SUPERUSER_USERNAME>"
DJANGO_SUPERUSER_PASSWORD= "<DJANGO_SUPERUSER_PASSWORD>"
DJANGO_SUPERUSER_EMAIL= "<DJANGO_SUPERUSER_EMAIL>"
```

## Deploying E6data Pov Tool setup in local network

### Run the docker compose command (This commands needs to be ran from docker-compose.yaml file location)

```console
docker-compose up -d
```


## Destroying E6data Pov Tool setup in local network

### Run the docker compose destory (This commands needs to be ran from docker-compose.yaml file location)

```console

docker-compose down

```

### Run the docker compose destory command (This commands needs to be ran from docker-compose.yaml file location)
This command will destory the volumes as well.

```console

docker-compose down -v

```

