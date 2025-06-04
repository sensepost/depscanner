#!/usr/bin/env python

"""
This script get a list of organisations in bug bounty programs from a .txt file
for each organisation domain, extract the hostname and search in github.com for that organisation repositories
for each repository, check if there is a file named requirements.txt or Pipfile or package.json
if the file exists, download it and search for dependencies
for each dependency, check if there is a package in the public repositories that matches the dependency
if the package does not exist, print the dependency and the repository where it was found and a message indicating that the package does not exist in the public repositories
"""
import argparse
import logging
from depscanner import DepScanner

logger = logging.getLogger(__name__)


# Parse arguments
# TODO: Add argument for number of stars to filter repositories. This will speed up the search and reduce the number of API rate limit hits
def argument_parser():
    """Parse the command line arguments"""
    parser = argparse.ArgumentParser(
        description="Find missing dependencies in Python, JavaScript, TypeScript, Ruby, and Golang projects"
    )
    source_group = parser.add_argument_group(
        "sources",
        description="Files containing domains, organisations names or repository names",
    )
    exclusive_source = source_group.add_mutually_exclusive_group(required=True)
    exclusive_source.add_argument(
        "-d", "--domains", help="File containing domain names", default=None
    )
    exclusive_source.add_argument(
        "-o", "--orgs", help="File containing GitHub organisation names", default=None
    )
    exclusive_source.add_argument(
        "-r", "--repos", help="File containing GitHub repository names", default=None
    )
    parser.add_argument(
        "-s",
        "--stars",
        help="Filter the repositories by the number of stars (default: 0)",
        default=0,
        type=int,
    )
    parser.add_argument("-t", "--token", help="GitHub PAT token for the API")
    parser.add_argument(
        "-P", "--proxy", help="Proxy for HTTP connections (debugging purposes)"
    )
    parser.add_argument(
        "-W", "--webhook", help="Discord webhook to receive missing packages details"
    )
    parser.add_argument(
        "-F",
        "--force",
        help="Force query GitHub and repositories API to refresh the database (default: False)",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "-L",
        "--level",
        help="Log level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    return parser.parse_args()


def logging_setup(log_level: str, logfile: str = "depscan.log"):
    """Setup the logging for the application"""
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(levelname)s - %(message)s",
        filename=logfile,
    )
    # Create console handler
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, log_level))
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(console)


############
### Main ###
############

# Init logging
arguments = argument_parser()
logging_setup(log_level=arguments.level)

# Kikc off the scanner with the arguments provided
ds = DepScanner(
    organisation_file=arguments.orgs,
    repositories_file=arguments.repos,
    domains_file=arguments.domains,
    gh_token=arguments.token,
    force=bool(arguments.force),
    proxy=arguments.proxy,
    logger=logger,
    webhook_url=arguments.webhook,
    stars=arguments.stars,
)
if ds.is_user_authenticated():
    ds.scan()
else:
    logger.error("User not autenticated successfully. Stopping")
