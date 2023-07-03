# Benchmark POV Tool <!-- omit in toc -->

The Benchmark POV Tool simplifies the complex process of benchmarking different compute engines. Follow these steps to get it up and running:

- [Prerequisites](#prerequisites)
  - [Install Docker \& docker-compose](#install-docker--docker-compose)
- [1. Install \& configure the Benchmark POV Tool using Docker](#1-install--configure-the-benchmark-pov-tool-using-docker)
  - [1.1 Configure Environment Variables (optional)](#11-configure-environment-variables-optional)
  - [1.2 Configure folder for persistence (option)](#12-configure-folder-for-persistence-option)
  - [1.3 Deploy the Benchmark POV Tool in a local environment](#13-deploy-the-benchmark-pov-tool-in-a-local-environment)
- [2. Configure the engines (e6data vs a target engine)](#2-configure-the-engines-e6data-vs-a-target-engine)
  - [2.1 Set up an e6data cluster](#21-set-up-an-e6data-cluster)
  - [2.2 Set up a Databricks cluster](#22-set-up-a-databricks-cluster)
- [3. Add the engines to the Benchmark POV Tool](#3-add-the-engines-to-the-benchmark-pov-tool)
  - [3.1 Login to the Benchmark POV Tool Admin Console](#31-login-to-the-benchmark-pov-tool-admin-console)
  - [3.2 Create an user account](#32-create-an-user-account)
  - [3.3 Add engines to the Benchmark POV Tool](#33-add-engines-to-the-benchmark-pov-tool)
- [4. Upload queries and run benchmarks](#4-upload-queries-and-run-benchmarks)
- [5. Uninstall the Benchmark POV Tool](#5-uninstall-the-benchmark-pov-tool)
  - [5.1 Destroying Benchmark POV Tool setup in local environment](#51-destroying-benchmark-pov-tool-setup-in-local-environment)


## Prerequisites
- **Docker**
    - Docker Engine v1.13.0+
    - docker-compose v1.10.0+
- **e6data**
    - Generate an e6data Personal Access Token
	- An active e6data cluster & connection details
	- Allowlist IP of the Benchmark POV Tool
- **Databricks**
    - Generate a Databricks Personal Access Token
	- An active Databricks cluster & connection details

### Install Docker & docker-compose
- [Docker Engine installation instructions](https://docs.docker.com/engine/install/)
- [docker-compose installation instructions](https://docs.docker.com/compose/install/)

## 1. Install & configure the Benchmark POV Tool using Docker
1. Download a copy of the e6-public-benchmarks repo from GitHub: [link](https://github.com/e6x-labs/e6-public-benchmarks)
2. Extract the contents to the directory where it will be installed.
3. Navigate to the `/pov` folder

### 1.1 Configure Environment Variables (optional)
- If you are installing the tool in a local environment, no edits to the `env` file are required.
- To install in remote server, please replace `REACT_APP_API_DOMAIN` with the domain/IP of the server.

```console
# REACT APP PARAMS
REACT_APP_API_DOMAIN= 'http://<SERVER_DOMAIN_OR_IP>:3001/api/'

# MYSQL PARAMS
MYSQL_ROOT_PASSWORD= "<MYSQL_ROOT_PASSWORD>"

#BACKEND PARAMS
MYSQL_WRITER_HOST= "<DB service name in docker-compose.yaml>"
DJANGO_SUPERUSER_USERNAME= "<DJANGO_SUPERUSER_USERNAME>"
DJANGO_SUPERUSER_PASSWORD= "<DJANGO_SUPERUSER_PASSWORD>"
DJANGO_SUPERUSER_EMAIL= "<DJANGO_SUPERUSER_EMAIL>"
```

### 1.2 Configure folder for persistence (option)

To preserve the Benchmark POV Tool's state (configuration settings, benchmark history, etc.), a folder named `pov_tool_storage` will be created inside the `/pov` folder. 

To set an alternative path edit the following line in the `docker-compose.yaml` file:

```docker
device: ./pov_tool_storage # change folder path
```

### 1.3 Deploy the Benchmark POV Tool in a local environment

**Run the docker-compose command**

> This commands needs to be run from the same directory as the docker-compose.yaml file

```console
docker-compose up -d
```

## 2. Configure the engines (e6data vs a target engine)

### 2.1 Set up an e6data cluster

1. Login to your e6data console. 
2. Select the workspace in which you wish to spin up the cluster.
3. [Create a catalog](https://docs.e6data.com/docs/catalogs) (if you haven’t created one already).
4. [Spin up a cluster](https://docs.e6data.com/docs/cluster) with a configuration equivalent to the engine you’ll be benchmarking against.
5. While waiting for the cluster spin up, [allow-list](https://docs.e6data.com/docs/access-control/ip-allowlisting) the IP you’ll be hosting the Benchmark POV tool on.
	- If you are running the Benchmark POV tool locally, use this [WhatIsMyIP.com](https://whatismyipaddress.com) to find your IP.
6. Generate a [Personal Access Token](https://docs.e6data.com/docs/access-control/ip-allowlisting)
7. Make note of the following, for later use:
	- e6data username
    - Personal Access Token
	- Cluster IP

### 2.2 Set up a Databricks cluster

1. Login to your Databricks workspace 
2. Generate a [personal access token](https://docs.databricks.com/dev-tools/auth.html#personal-access-tokens-for-users)
3. Spin up a cluster with a configuration equivalent to the engine you’ll be benchmarking against.
3. Navigate to the `Configuration` tab of the cluster.
4. Make note of the following, for later use:
	- Server Hostname
	- HTTP Path

## 3. Add the engines to the Benchmark POV Tool

### 3.1 Login to the Benchmark POV Tool Admin Console
1. The Admin Console can be accessed here:
   1. http://localhost:3001/api/ (if locally hosted)
   2. http://<SERVER_DOMAIN_OR_IP>:3001/api/ (if hosted remotely)
2. Username: admin (from env parameter DJANGO_SUPERUSER_USERNAME)  
3. Password: password (from env parameter DJANGO_SUPERUSER_PASSWORD)
> It is advisable to change the username and password after the first login.

### 3.2 Create an user account
1. Navigate to  `Home > User > Users` & click `+ Add`
2. Create a user by providing a username, email address & password.
    - These user credentials will be used to login to the frontend.
3. Click `SAVE`

### 3.3 Add engines to the Benchmark POV Tool
1. Navigate to `Benchmarks > Benchmark_ips` & click `+ Add`
2. Fill in the following details:
   - Cloud Type: *cloud service provider*
   - Database name: *database that will be queried, **this should be the same for both engines***
   - e6data IP: *IP of the e6data cluster* 
   - e6data User: *username provided in the connector tab* 
   - e6data Token: *access token generated by the user*
   - DBR IP: *Hostname of the Databricks cluster* 
   - DBR HTTP: *HTTP path of the Databricks cluster*
3. Click `SAVE`

## 4. Upload queries and run benchmarks
1. Access the frontend of the Benchmark POV Tool:
   1. http://localhost:3000/login/ (if locally hosted)
   2. http://<SERVER_DOMAIN_OR_IP>:3000/login/ (if hosted remotely)
2. Login using the user credentials created in step 3.2
3. Click `Create Benchmark` 
4. Fill in the following details:
   1. Name your benchmark: *provide a name for this benchmark*
   2. e6data vs: *select the engine you want to compare e6data against*
   3. e6data cluster cost (/hr): *the hourly cost of the e6data cluster*
   4. vs cluster cost (/hr): *the hourly cost of the cluster to benchmark against*
   5. Run concurrently: *run the queries sequentially or concurrently*
      1. Concurrent queries: *number of queries to run in parallel*
      2. Ramp up time: *interval between running batches of concurrent queries (in seconds)*
5. Click `Next`
6. Upload a CSV containing a list of queries.
   1. Download the sample CSV to understand the required structure.
7. Click `Configure`
8. Wait for all the queries to complete running.
9.  The time taken to run each query & the cost incurred will be displayed.
   1.  A detailed report can be downloaded for further analysis.

## 5. Uninstall the Benchmark POV Tool

### 5.1 Destroying Benchmark POV Tool setup in local environment

**Run the docker-compose destroy command**
> This commands needs to be run from the same directory as the docker-compose.yaml file

```console
docker-compose down
```

**Run the docker-compose destroy command & delete volumes**
> This commands needs to be run from the same directory as the docker-compose.yaml file

```console
docker-compose down -v
```
