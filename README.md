# CAT Module - Python
This module serves as a backend for adaptive and classical online-tests in GeoGebra.

## Getting Started
### Preconditions
Make sure that [Python](https://www.python.org/downloads/) (3.7+) and [Redis](https://redis.io/topics/quickstart)
are installed. 

### Setup
1. Start the redis server and add the configurations to the `config.py` file.
2. Install all modules defined in the `requirements.txt` via:
   ```shell
   $ pip install -r requirements.txt
   ```

### Running the module
Start the [uvicorn](https://www.uvicorn.org/) server like in the `Procfile`, e.g.:
```shell
$ uvicorn main:CATModule --host 127.0.0.1 --port 80
```
The application is now accessible on `localhost` (http://127.0.0.1:80/quiz/question).

## Documentation
The API documentation can be accessed under `/docs`.

## Tests
No tests are currently implemented, this will be done in the later stages of the project.

## Deployment
1. Create a [ElastiCache](https://eu-west-1.console.aws.amazon.com/elasticache/home?region=eu-west-1) Redis instance.
2. Put its *Primary Endpoint* to the `config.py` file.
3. Create an [Elastic Beanstalk](https://eu-west-1.console.aws.amazon.com/elasticbeanstalk/home?region=eu-west-1)
   environment running *Python 3.7 running on 64bit Amazon Linux 2*.
4. Connect the project to the environment using the [eb cli](https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/eb-cli3-install.html):
   ```shell
   $ eb init
   ```
5. Deploy the current version:
   ```shell
   $ eb deploy
   ```
