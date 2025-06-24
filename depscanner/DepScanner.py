import time
import logging
import re
import json
from urllib.parse import urlparse
# from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from os.path import exists as file_exist
from functools import lru_cache
import urllib3

import yaml
import requests

from depscanner.Utils import get_response_emoji, get_stars_score
from depscanner.ModfileParser import ModfileParser, DependencyInfo
from depscanner.DiscordBell import DiscordBell
from depscanner.MongoManager import MongoManager
from depscanner.models.Package import Package
from depscanner.models.Dependency import Dependency
from depscanner.models.Scope import Scope
from colors import Colors

from enum import Enum,auto

# Disable urllib3 warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# A goog bounty list is available at: https://github.com/nashcontrol/bounty-monitor/blob/master/bug-bounty-list.txt or https://github.com/projectdiscovery/public-bugbounty-programs

# TODO: To prevent constantly polling GitHub for companies repositories, we can save the information in a MongoDB database
# Then, unless we specify the -f (force) flag, we go to the repositories saved in the database instead of querying GitHub
# This way, we can save time and resources

class SearchOutcome(Enum):
    GOOD=auto()
    BAD=auto()
    ERROR=auto()
    INFORMATION=auto()
    UNKNOWN=auto()

class DepScanner:
    """This class is responsible for scanning the dependencies of the repositories or domains provided"""

    def __init__(
        self,
        gh_token: str,
        logger: logging.Logger,
        force: bool = False,
        proxy: str = None,
        organisation_file: str = None,
        repositories_file: str = None,
        domains_file: str = None,
        config: str = "config.yml",
        webhook_url: str = None,
        stars: int = 0,
    ):

        self.targetfile = organisation_file
        self.gh_token = gh_token
        self.proxy = proxy
        self.force = force
        self.logger = logger
        self.config = config
        self.minimum_stars = stars
        self.target_repository_names = self.load_repositories(repositories_file)
        self.target_organisation_names = self.load_organisations(organisation_file)
        self.domain_names = None
        if self.target_organisation_names is None or len(self.target_organisation_names)==0:
            self.target_organisation_names = self.load_from_domain_names(
                domains_file
            )  # Yes, I will just extract the tld from the domains to obtain an organisation name list
        self.repos_to_explore = (
            list()
        )  # A list of json objects containing the repositories to explore returned by the GitHub API
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        self.proxies = {}
        self.webhook_url = webhook_url
        self.bell = DiscordBell(webhook_url=self.webhook_url, logger=self.logger)

        # Setup search API token
        if self.gh_token:
            self.headers["Authorization"] = f"Bearer {self.gh_token}"
        else:
            self.logger.warning("No GitHub API token provided. Rate limits may apply.")

        # Set proxies
        if self.proxy:
            self.proxies["http"] = self.proxy
            self.proxies["https"] = self.proxy

        # Init the modparser object
        self.modparser = ModfileParser(
            proxies=self.proxies, headers=self.headers, logger=self.logger
        )

        # Read config settings
        self.api_base = None
        self.lang_repos = None
        self.repos_depfiles = None
        self.pub_repos = None
        self.jitter = None
        self.backoffbase = None
        self.mongo = None
        # Load data from configuration file, including the mongo configuration
        self.load_config()
        # Initialize mongo connection
        self.mongomgr = MongoManager(
            host=self.mongo["host"],
            port=self.mongo["port"],
            database=self.mongo["database"],
            username=self.mongo["username"],
            password=self.mongo["password"],
            logger=self.logger
        )

        self.current_repo_index = 0  # Track the current repository being processed

    #### Functions ####
    def load_repositories(self, file: str) -> list:
        """Load the repositories from a file into the class variable"""
        valid_repos = []
        if file is not None and file_exist(file):
            with open(file, "r", encoding="UTF-8") as f:
                for line in f.readlines():
                    if (
                        re.match(r"^[a-zA-Z0-9_-]+\/[a-zA-Z0-9_-]+$", line.strip())
                        is not None
                    ):
                        valid_repos.append(line.strip())
        return valid_repos

    def load_from_domain_names(self, file: str) -> list:
        """Load the domains from a file into the class variable"""
        self.domain_names = []
        if file is not None and file_exist(file):
            with open(file, "r", encoding="UTF-8") as f:
                # Extract the hostname from the domain
                self.domain_names = set(
                    [domain.split(".")[0] for domain in f.read().splitlines()]
                )
        return self.domain_names

    def load_organisations(self, file: str) -> list:
        """Load the organisations from a file into the class variable"""
        valid_orgs = []
        if file is not None and file_exist(file):
            with open(file, "r", encoding="utf-8") as f:
                for line in f.readlines():
                    if re.match(r"^[a-zA-Z0-9_-]+$", line.strip()) is not None:
                        valid_orgs.append(line.strip())
        return valid_orgs

    def load_config(self):
        """Load the configuration from the config file"""
        try:
            with open(self.config, "r", encoding="UTF-8") as f:
                config = yaml.safe_load(f)
                # Update class variables from config
                self.api_base = config.get("api_base")
                self.lang_repos = config.get("lang_repos")
                self.repos_depfiles = config.get("repos_depfiles")
                self.pub_repos = config.get("pub_repos")
                self.jitter = config.get("jitter")
                self.backoffbase = config.get("backoffbase")
                self.request_timeout = config.get("request_timeout")
                self.mongo = config.get("mongo")
                self.db_refresh_hours = config.get("db_refresh_hours")
                self.logger.debug(f"Loaded configuration from {self.config}")
        except FileNotFoundError:
            self.logger.warning(f"Config file {self.config} not found, using defaults")
        except yaml.YAMLError as e:
            self.logger.error(f"Error parsing config file {self.config}: {e}")
            raise

    def get_org_repositories_from_database(self, organisation: str) -> list:
        """Pull the repositories list from the local database"""
        # If we have recent repositories for this organisation in the database, retrieve these repositories
        return list(self.mongomgr.get_company_repos(organisation))
    
    def get_org_repositories_online(self, organisation: str) -> list:
        """Get the repositories in github for a given organisation"""
        # If we don't have any repository in the
        # We set the maximum number of repositories to pull
        repos = []
        url = f"https://api.github.com/orgs/{organisation}/repos?per_page=100"
        response = requests.get(
            url,
            headers=self.headers,
            proxies=self.proxies,
            verify=False,
            timeout=self.request_timeout,
        )
        if response.status_code == 200:
            # Insert data into Mongo
            self.mongomgr.save_company_repos(json.loads(response.text))
            repos = response.json()
            # Save the number of repositories of the organisation
            self.mongomgr.save_or_update_explored_org(name=organisation, number_repos=len(repos))
        elif response.status_code == 404:
            self.mongomgr.save_or_update_explored_org(name=organisation, number_repos=0)
        else:
            self.logger.error(
                f"Error getting repositories for {organisation}: {response.text}"
            )

        return repos

    def search_registries(self, dependency: Dependency) -> Dependency:
        """Search for a package in the public registries"""
        # Check if this is an URL
        # if so, search by url
        # The only case where URls are specified in the requirements is ruby
        # for Go, the url can also be found in pkg.go.dev by looking for the url deplib_url = f"https://pkg.go.dev/{url}"
        package = Package.from_dict(list(self.mongomgr.get_packages(_id=dependency.package_id))[0])

        # Logic to see if the package.url is not None, if it is, we search it by name
        if package.url is not None and len(package.url) > 0:
            package = self.search_registries_by_url(package)
        elif package.name is not None and len(package.name) > 0:
            package = self.search_package_in_registries(package)
        
        # Save dependency info after updating the package info we just retrieved
        dependency.package = package
        return dependency

    @lru_cache
    def _get_package_scope(self, package: Package) -> str:
        """This method parses the name of a package if it's in npmjs.org and returns the scope name if it has one"""
        scope = None
        if package.registry=="registry.npmjs.org" and package.name.startswith("@"):
            # Check if the package is a scoped package
            scope = package.name.split("/")[0].replace("@", "")
        return scope
    
    # If the package is JavaScript or TypeScript and the registry is npmjs.org, we need to see if it's a scoped package
    # Scoped packages are the ones starting with @scop/packagename. In this case, we need to search for the package in the registry
    # https://registry.npmjs.org/-/org/fmtorre/package
    @lru_cache
    def _search_scope_in_npm(self, package: Package) -> tuple:
        """Search for a scope/organisation name in nmp registry"""
        
        if (package.scope is not None and len(package.scope)>0):
            # This API call is made when nmp cli issues this command:
            # npm access list packages @scope
            scope_response = requests.head(
                f"https://registry.npmjs.org/-/org/{package.scope}/package",
                proxies=self.proxies,
                verify=False,
                allow_redirects=True,
                timeout=self.request_timeout,
            )
            return scope_response.status_code
        else:
            return 0

    def search_registries_by_url(self, package_object: Package) -> Package:
        """
        Search for a package in the public repositories by its URL
        If the package dictionary already contains a valid 'url' key, it will use that URL to search for the package
        """

        # package_database = list(self.mongomgr.get_packages(package_name=package_object.name,language=package_object.language))
        # if not package_database:
        # Request package info from the final URL.
        # Using HEAD request to avoid downloading the package info
        MAX_RETRIES=5
        MAX_REQUEST_RETRIES=5
        success_search_pubrepo = False
        repos_wall_hit_times = 0
        request_error_count = 0
        # Prepend the schema if not found in the url
        package_url = package_object.url
        if "://" not in package_url:
            package_url = "https://" + package_url
        package_netloc = urlparse(package_url).netloc

        while not success_search_pubrepo and repos_wall_hit_times<MAX_RETRIES and request_error_count<MAX_REQUEST_RETRIES:
            try:
                # Get the information from the registry URL
                headers = {
                    "Accept": "application/vnd.npm.install-v1+json; q=1.0, application/json; q=0.8, */*"
                }
                response = requests.get(
                    package_url,
                    proxies=self.proxies,
                    verify=False,
                    allow_redirects=True,
                    headers=headers,
                    timeout=self.request_timeout,
                )
            except requests.exceptions.RequestException as re:
                self.logger.error(f"Exception when contacting the HTTP server: {re}")
                request_error_count+=1
                break

            # Now, fill up the package object information
            try:
                # Default values for response codes
                package_object.present = False
                package_object.registry = package_netloc
                # Update values of the package dependent on the returned status code
                package_object.response_code = response.status_code
                package_object.present = (package_object.response_code == 200)
                
                # Deal with npmjs scopes:
                # TODO: Refactors this. I shall remove the scope information from the package object and just link to the scope ObjectID 
                # to reduce redundancy
                package_object.scope = self._get_package_scope(package_object)
                # If the package has a scope
                if (package_object.scope is not None and len(package_object.scope)>0):
                    scopes=list(self.mongomgr.get_scopes(name=package_object.scope))
                    # The scope was not in our DB, so ask online
                    package_object.scope_response_code = self._search_scope_in_npm(package_object)
                    if  (len(scopes)==0):
                        self.mongomgr.update_scope(
                            Scope(
                                name=package_object.scope,
                                response_code=package_object.scope_response_code,
                                present=(package_object.scope_response_code==200)
                            )
                        )
                    else:
                        if (len(scopes)>1):
                            self.logger.warning(f"More than one scope in the db with name {package_object.scope}. Investigate.")
                        scope=Scope.from_dict(scopes[0])
                        package_object.scope_response_code = scope.response_code
                        package_object.scope_present = (package_object.scope_response_code == scope.response_code)

                # Check if we have to backoff for a while as we received a forbidden or rate limit response
                if package_object.response_code  in [429, 403]:
                    # Backoff for a while
                    self.logger.error(
                        f"Error searching for {package_url}: Got response code {package_object.response_code}  {get_response_emoji(package_object.response_code)}"
                    )
                    repos_wall_hit_times += 1
                    self._backoff(repos_wall_hit_times)
                else: #if package_object.response_code == 200:
                    success_search_pubrepo = True
                    # Check if the URL is returning JSON and store the response as metadata
                    # Generalising the content-type to 'json', as npmjs returns this weird content-type 'application/vnd.npm.install-v1+json'
                    if 'json' in response.headers['Content-Type']:
                        package_object.metadata = json.loads(response.text)
                    else:
                        package_object.metadata = response.text

            except json.JSONDecodeError as je:
                self.logger.error(f"Error decoding the JSON response of {package_url}. Did we store the correct API endpoint?: {je}")

            except NameError as ne:
                self.logger.error(f"Error searching for {package_url}: {ne}")

            except Exception as e:
                self.logger.error(f"Error searching for {package_url}: {e}")
        
        if repos_wall_hit_times>MAX_RETRIES:
            raise Exception(f"Multiple errors searching for {package_url}")
        
        return package_object

    # Use a cache of packages, so it does not go out online if we recently resolved the package localy
    @lru_cache(maxsize=128)
    def search_package_in_registries(self, package: Package) -> Package:
        """
        Search for a package in the public repositories by its name.
        This function will build an URL based on the language and the package name.
        Returns a tuple with the package object, and two HTTP response codes for the package itself and the scope for npmjs packages.
        The function uses an lru_cache for previously searched packages.
        This should speed up the search and prevent HTTP communications.
        """
        if package.language == "Python":
            package.url = f"https://pypi.org/pypi/{package.name}/json"
        elif package.language == "JavaScript" or package.language == "TypeScript":
            package.url = f"https://registry.npmjs.org/{package.name}"
        elif package.language == "Ruby":
            package.url = f"https://rubygems.org/api/v1/gems/{package.name}.json"
        elif package.language == "Go":
            # AFAIK, there is no API to retrieve JSON data from go.dev
            package.url = f"https://pkg.go.dev/{package.name}"
        else:
            self.logger.error(f"Unknown registry for: {package.language}")
            return package

        # Now we search for the url that we built
        return self.search_registries_by_url(package)

    def _backoff(self, wall_hit_times: int):
        """Sleep for an increasing amount of time to avoid hitting the rate limit"""
        t = self.backoffbase * wall_hit_times
        self.logger.info(f"😴 Sleeping for {t} seconds")
        time.sleep(t)

    def is_user_authenticated(self):
        """Check if the user is authenticated against the GitHub API"""
        response = requests.get(
            "https://api.github.com/user",
            headers=self.headers,
            proxies=self.proxies,
            verify=False,
            timeout=self.request_timeout,
        )
        if "login" in response.json().keys() and "id" in response.json().keys():
            self.logger.debug(f"Authenticated as {response.json()['login']}")
            return True
        else:
            self.logger.error(
                f"Error authenticating user against github API: {response.text}"
            )
            return False

    def _build_log_message(
        self,
        outcome: int,
        package_name: str,
        dependency_semver: str,
        gh_repo: str,
        depfile_path: str,
        package_url: str,
        response_code: int,
        scope_response_code: int = None,
        local: bool = None
    ) -> str:
        msg = f"📦 '{package_name} ({dependency_semver})' required by '{gh_repo}' in {depfile_path} in {package_url} response code: [{response_code} {get_response_emoji(response_code)} "
        if scope_response_code:
            msg += f" / scope {scope_response_code} {get_response_emoji(scope_response_code)}]"
        else:
            msg += "]"
        
        # Add local information or fresh from the web 
        if local:
            msg += " 🏠 (local)"
        else:
            msg += " 📡 (remote)"
        
        # Print the message with nice colors
        if outcome == SearchOutcome.GOOD:
            msg = f"[{Colors.green('+')}] - {msg}"
        elif outcome == SearchOutcome.BAD:
            msg = f"[{Colors.red('-')}] - {msg}"
        elif outcome == SearchOutcome.INFORMATION:
            msg = f"[{Colors.gray('i')}] - {msg}"
        elif outcome == SearchOutcome.UNKNOWN:
            msg = f"[{Colors.yellow('?')}] - {msg}"
        else:
            msg = f"[{Colors.gray('?')}] - {msg}"

        return msg

    def _build_discord_message(
        self,
        package_name: str,
        dependency_semver: str,
        package_url: str,
        gh_repo: str,
        repo_stars: int,
        depfile_path: str,
        response_code: int,
        scope_response_code: int = None,
        local: bool = None,
    ) -> str:
        msg = f"""
**Repository**: [{gh_repo}](https://github.com/{gh_repo})
**Stars**: {get_stars_score(repo_stars=repo_stars)} [{repo_stars}]
**File**: [{depfile_path}](https://github.com/{gh_repo}/blob/master/{depfile_path})
**Dependency**: {package_name} ({dependency_semver})
**Repo URL**: {package_url} [{response_code} {get_response_emoji(response_code)}]
"""
        # If this is a scoped nodejs package:
        if scope_response_code:
            msg += f"**Scope Response**: [{scope_response_code} {get_response_emoji(scope_response_code)}]"
        # If the package was found in the local database add this
        if local:
            msg += """
**Source**: Local 🏠
            """
        else:
            msg += """
**Source**: Remote 📡
            """

        return msg

    def _report_package_search_result(
            self, 
            dependency: Dependency, 
            repo_stars: int):
        """This function creates the log entry and Discord notification to informa about the package search result"""
        discord_msg = None
        package = dependency.package

        # For each result save it in the DB
        outcome = SearchOutcome.UNKNOWN
        if package.response_code == 404:
            # Check if this is a scoped package, then we have to take into account the scope to indicate whether it is hijackable or not
            # This package is not present, but the scope exists, so it's not hijackable
            if package.scope_response_code is not None:
                if package.scope_response_code == 200:
                    outcome = SearchOutcome.BAD
                    # existing_packages.append(package.name)
                elif package.scope_response_code == 404:
                    outcome = SearchOutcome.GOOD
                    # not_found_packages.append(package.name)
            else:
                # This package is not scoped, so it's hijackable
                outcome = SearchOutcome.GOOD
                # not_found_packages.append(package.name)
        elif package.response_code == 200:
            outcome = SearchOutcome.BAD
            # existing_packages.append(package.name)
        else:
            outcome = SearchOutcome.BAD
            # not_found_packages.append(package.name)

        # Print logging information of this package
        self.logger.info(
            self._build_log_message(
                outcome=outcome,
                package_name=package.name,
                dependency_semver=dependency.semver,  
                gh_repo=dependency.repo_name,
                depfile_path=dependency.dependency_file,
                package_url=package.url,
                response_code=package.response_code,
                scope_response_code=package.scope_response_code,
            )
        )
        # Send discord message if there is a good outcome (good for the hacker, of course)
        if outcome == SearchOutcome.GOOD:
            discord_msg = self._build_discord_message(
                package_name=package.name,
                package_url=package.url,
                dependency_semver=dependency.semver,  # TODO: Where to get the semver of this dependency? it's no longer part of hte package object
                gh_repo=dependency.repo_name,
                repo_stars=repo_stars,
                depfile_path=dependency.dependency_file,
                response_code=package.response_code,
                scope_response_code=package.scope_response_code,
            )
            self.bell.ping(msg=discord_msg)

    def search_dependencies_in_registries(
        self,
        dependencies_to_search: list,
        repo_stars: int
    ):
        """
        Search for packages of the GitHub repository in the public registries
        It will do a parallel search of the packages names using the ThreadPoolExecutor to speed up the search
        """
        try:
            with ThreadPoolExecutor(max_workers=len(dependencies_to_search)) as executor:
                futures = [
                    # Create a Package object for each call
                    executor.submit(
                        self.search_registries,
                        dependency,
                    )
                    for dependency in dependencies_to_search
                ]
                # Change from set() to list() since dictionaries are not hashable
                results = [future.result() for future in futures]
        except Exception as e:
            self.logger.exception(f"Error searching for one of the dependencies: {dependencies_to_search}. Moving on.")

        # The scope_response_code is used to check if the scope exists in the npm registry, but not of the other package registries
        # If the scope exists, it's not hijackable
        for returned_dependency in results:
            returned_package = returned_dependency.package
            
            # Display the log message and report to Discord the result
            self._report_package_search_result(
                returned_dependency,
                repo_stars=repo_stars
                )

            # Save the result in the DB
            self.mongomgr.update_package(returned_package)
            returned_dependency.package_id = returned_package._id
            # Create the relation between the package and the repository
            self.mongomgr.update_repository_dependency(returned_dependency)

    def _is_date_fresh(self, updated: datetime) -> bool:
        d = datetime.now()-updated
        return ((d.seconds)<(self.db_refresh_hours*3600)) 

    def _get_repository_data_from_database(self, target_repo_name):
        """Gets the repository data from the local database"""
        repositories = list(self.mongomgr.get_repositories(repo_name=target_repo_name))
        if (len(repositories)>1):
            self.logger.debug(f"There are {len(repositories)} repositories with name {target_repo_name} in the database. Investigate.")
    
        # Select only the most recent repository from the resulting list of repositories
        return repositories[0]

    def _get_repository_data_online(self, repo_name: str) -> dict:
        """Get the repository data from the GitHub API"""
        # Check if the repository data is already in our database and return that one

        repository={}
        url = f"https://api.github.com/repos/{repo_name}"
        response = requests.get(
            url,
            headers=self.headers,
            proxies=self.proxies,
            verify=False,
            timeout=self.request_timeout,
        )
        if response.status_code == 200:
            self.mongomgr.save_single_repository(json.loads(response.text))
            repository = response.json()
        else:
            self.logger.error(
                f"Error getting repo info for {repo_name}: {response.text}"
            )
        
        return repository

    def _retrieve_dependencies_from_files(self, repo_name: str, repo_language: str):
        """Search for dependency files in the repository from GitHub API"""

        success_searching = False
        github_wall_hit_times=0
        dependencies = []
        while not success_searching:
            self.logger.info(
                f"Searching for dependencies of {repo_name} ({github_wall_hit_times} times attempted)"
            )

            # query for each dependency file
            # Using GitHub search API: https://api.github.com/search/code?q=filename:package.json+repo:org/repo
            # Note: This requires authentication for better rate limits

            # Search for requirement files that match the language this project is written with
            gb_target_repo = self.lang_repos[repo_language]
            for dep_file_name in self.repos_depfiles[gb_target_repo]:
                # for dep_file_name in set(PUB_REPOS.keys()):
                self.logger.debug(
                    f"Searching for {dep_file_name} in repository {repo_name}..."
                )
                endpoint = f"{self.api_base}/search/code?q=filename:{dep_file_name}+repo:{repo_name}"
                response = requests.get(
                    endpoint,
                    headers=self.headers,
                    proxies=self.proxies,
                    verify=False,
                    timeout=self.request_timeout,
                )

                # Check the status of the request
                if response.status_code == 200:
                    dependencies += response.json()["items"]
                    success_searching = True
                elif response.status_code == 403 or response.status_code == 429:
                    self.logger.info(f"Rate limit exceeded searching the dependency {dep_file_name} of {repo_name}")
                    # Throttle the requests
                    github_wall_hit_times += 1
                    self._backoff(github_wall_hit_times)
                else:
                    self.logger.error(
                        f"Error searching for {dep_file_name} of {repo_name}: {response.text} [{response.status_code}]"
                    )
      
        return dependencies
    
    def _populate_dependencies(self, gh_repo: dict, dep: dict, required_packages: list) -> list:
        """This function populates an array with the dependencies we need to analyse"""
        
        # Initialize the depencendies list
        dependencies=[]

        # Fill some dependency helper variables
        dep_file_name=dep['name']
        dep_file_path=dep['path']

        # Fill some repository helper variables
        repo_id = gh_repo["id"]
        repo_language = gh_repo["language"]
        repo_full_name = gh_repo["full_name"]
        repo_stars = gh_repo["stargazers_count"]

        for required_package in required_packages:
            if dep_file_name not in self.pub_repos.keys():
                self.logger.error(
                    f"Dependency file {dep_file_name} not found in the recogniced dependency files. Skipping."
                )
                continue

            registry_name = self.pub_repos[dep_file_name]

            # Retrieve all packages we have already explored (no filter in the query)
            repo_packages_in_db = self.mongomgr.get_packages(
                registry=registry_name
            )
            repo_package_in_db_names = set()
            for ep in repo_packages_in_db:
                repo_package_in_db_names.add(ep["name"])

            # If the required package is already in the database
            if required_package.name in repo_package_in_db_names:
                self.logger.debug(
                    f"[{Colors.gray('i')}] Package {required_package.name} is already in the database. Creating the dependency only."
                )
                
                packages = list(self.mongomgr.get_packages(package_name=required_package.name,registry=registry_name))
                if (len(packages)>1):
                    self.logger.warning(f"Warning: More than one document in the database with package name {required_package.name} in the registry {registry_name}. Investigate.")
                
                package_obj=Package.from_dict(packages[0])
            # If the package name is not in our local database
            elif (
                required_package.name is not None
                and len(required_package.name) > 0
            ):
                
                # Create empty package and save it in the database
                package_obj = Package(
                    name=required_package.name,
                    registry=registry_name,
                    language=repo_language,
                    url = required_package.url
                ) 
                
                # Once the package object is created, either from the database or dummy (as it's not in the DB)
                self.mongomgr.save_package(package_obj)
            else:
                self.logger.error(
                    f"There was an error with the name of required package: '{required_package.name}'"
                )
            
            # We create a dependency object and save it in the database, then we update the package info in the database
            dependency = Dependency(
                repo_id=repo_id,
                repo_name=repo_full_name,
                package_name=package_obj.name,
                package_id=package_obj._id,
                dependency_file=dep_file_path,
                semver=required_package.semver
            )
            
            # Check if the dependency link already exists
            existent_dependencies = list(self.mongomgr.get_dependencies(repo_id=repo_id,package_id=package_obj._id))
            if (len(existent_dependencies)==0):
                # Save the dependency with dummy package record
                self.mongomgr.save_repository_dependency(dependency=dependency) 
                # The dependency was not in the database, so store it for later online search
                dependencies.append(dependency)
            else:
                self.logger.debug(f"Dependency relation between repository '{repo_full_name}' and package '{package_obj.name}' (_id: {package_obj._id}) was already in the DB")
                # No need to search for this package online unless the flag --force is specified
                package_updated_date = package_obj.updated
                # If the download is forced or the data is not fresh, download it
                if self.force or not self._is_date_fresh(package_updated_date):
                    # Force the search in online repositories of this package
                    self.logger.info(f"Forcing the online search due to the --force flag was specified or package info not being fresh.")
                    dependencies.append(dependency)   
                else:
                    # No need to search/refresh this dependency, but if the package was a 404, it should reported anyway
                    package=Package.from_dict(self.mongomgr.get_packages(_id=dependency.package_id)[0])
                    if not package.present and package.response_code is not None:
                        # If the package has a scope, check if it's not present:
                        if package.scope is None or (package.scope is not None and package.scope_response_code==404):
                            # Report it in the log and discord
                            log_msg = self._build_log_message(
                                outcome=SearchOutcome.GOOD,
                                package_name=package.name,
                                dependency_semver=dependency.semver,
                                gh_repo=repo_full_name,
                                depfile_path=dependency.dependency_file,
                                package_url=package.url,
                                response_code=package.response_code,
                                scope_response_code=package.scope_response_code,
                                local=True
                            )
                            self.logger.info(log_msg)
                            # Now discord message
                            discord_msg = self._build_discord_message(
                                package_name=package.name,
                                dependency_semver=dependency.semver,
                                package_url=package.url,
                                gh_repo=repo_full_name,
                                repo_stars=repo_stars,
                                response_code=package.response_code,
                                scope_response_code=package.scope_response_code,
                                depfile_path=dependency.dependency_file,
                                local=True
                            )
                            self.bell.ping(discord_msg)

        return dependencies

    def scan_repositories(self):
        """Scan a list of repository names provided by the user"""
        github_wall_hit_times = 0
        # valid_languages = set([pb for pb in self.lang_repos.keys()])
        current_iteration_existing_packages = []
        not_found_packages = []
        repo_count = 0

        for gh_repo in self.repos_to_explore:
            self.current_repo_index += 1
            repo_id = gh_repo["id"]
            repo_language = gh_repo["language"]
            # Get the repository path
            repo_full_name = gh_repo["full_name"]
            repo_stars = gh_repo["stargazers_count"]
            # Make the stars easily readable from 1 to 5
            repo_count += 1
            header_msg = f"* 👀 Repository #{repo_count}/{len(self.repos_to_explore)}: {repo_full_name} - {get_stars_score(repo_stars=repo_stars)} [{repo_stars}] (Lang: {repo_language}) 👀 *"
            self.logger.info("*" * len(header_msg))
            self.logger.info(header_msg)
            self.logger.info("*" * len(header_msg))

            # Skip repos not written in the languages we cover here
            if repo_language not in self.lang_repos.keys():
                self.logger.info(
                    f"⏭️ 👅 Skipping analysis of repository {repo_full_name} because it is not any of {', '.join(self.lang_repos.keys())}"
                )
                continue

            if repo_stars < self.minimum_stars:
                self.logger.info(
                    f"⏭️ ⭐ Skipping analysis of repository {repo_full_name} because it has less than {self.minimum_stars}"
                )
                continue

            # Search for dependencies in the files of the repository
            dependencies = self._retrieve_dependencies_from_files(
                repo_name=repo_full_name,
                repo_language=repo_language
            )
            
            self.logger.debug(
                f"Found {len(dependencies)} dependency files in {repo_full_name}: {', '.join(map(lambda x: x['path'], dependencies))}"
            )

            # Parse each dependency file
            for dep_item in dependencies:
                # Parse the dependency file
                required_packages = self.modparser.get_and_parse_depfile(item=dep_item)
                
                # Populate a list of dependencies to search in parallel
                dependencies_to_search = self._populate_dependencies(
                    gh_repo=gh_repo,
                    dep=dep_item,
                    required_packages=required_packages
                    )  

                # =================================== #
                # = Parallel search of dependencies = #
                # =================================== #
                if (len(dependencies_to_search)>0):
                    # Search packages in parallel
                    self.search_dependencies_in_registries(
                        # packages_to_search=packages_to_search,
                        dependencies_to_search=dependencies_to_search,
                        repo_stars=repo_stars
                    )
                else:
                    self.logger.debug("All packages were already in our database. Not searching online for these. Only dependencies may have been updated in the database")

    def _get_explored_repositories(self) -> dict:
        # Obtain the repositories we already explored
        explored_repositories = list(self.mongomgr.get_repositories())
        explored_repositories_updated = dict()
        if (explored_repositories is not None):
            for eo in list(explored_repositories):
                explored_repositories_updated[eo['full_name'].casefold()]=eo['updated']

        return explored_repositories_updated

    def _get_explored_organisations(self) -> dict:
        """Obtain the organisations and repositories we already explored and are stored in the database"""
        explored_orgs = self.mongomgr.get_explored_orgs()
        explored_organisation_updated = dict()
        if (explored_orgs is not None):
            for eo in list(explored_orgs):
                explored_organisation_updated[eo['name'].casefold()]={
                        "updated": eo['updated'],
                        "number_repos": eo['number_repos']
                    }
        return explored_organisation_updated

    def _prepare_organisations_scan(self) -> int:
        """
        Prepare the list of repositories to analyse obtained from the list of organisation names provided in the arguments or derived from the domain list.
        If the organsation was recently explored (less than the fresh number of hours) and the force flag was not specified, the organsation information is not downloaded from GitHub.
        Then we explore the list of repositories obtained from GitHub or the local database.
        If the repository was recently explored (less than the fresh number of hours) and the force flag was not specified, the repository is ignored.
        Returns the number of repositories to scan.
        """

        # Get the list of organisation names and repositories with their updated status
        explored_organisation_updated=self._get_explored_organisations()

        org_count=0
        download_from_gh=False
        # Iterate through the target organisations specified
        for target_org_name in self.target_organisation_names:
            org_count+=1
            # Check wether the oganisation is in the local database
            organisation_is_fresh=False
            organisation_num_repos=None
            # If the organisation is currently in the database, check if it's fresh and the number of repositories it has
            if target_org_name.casefold() in explored_organisation_updated:
                organisation_is_fresh=self._is_date_fresh(explored_organisation_updated[target_org_name]['updated'])
                organisation_num_repos=explored_organisation_updated[target_org_name]['number_repos']
            
            # Now, take the decisions of using the local database cache or pull from GitHub
            # If force was specified, download from GitHub
            if self.force:
                download_from_gh=True
            # If the data in the local cache is not fresh, download from GitHub
            elif not organisation_is_fresh and (organisation_num_repos and organisation_num_repos>0):
                download_from_gh=True
            # If the number of repos we found last time was 0, no need to download anything from GitHub, they have no repositories
            else:
                download_from_gh=False
            
            # If download flag is set, download, else use the local database cache
            if download_from_gh:
                org_repos = self.get_org_repositories_online(target_org_name)
            # No need to download from GitHub, use the local database cache
            else:
                org_repos = self.get_org_repositories_from_database(target_org_name)

            # Print logging message:
            org_header_msg = f"= 🏢 Organisation #{org_count}/{len(self.target_organisation_names)}: {target_org_name} 🏢 ="
            self.logger.info("=" * len(org_header_msg))
            self.logger.info(org_header_msg)
            self.logger.info("=" * len(org_header_msg))
            msg=f" Obtained {len(org_repos)} repositories "
            if not download_from_gh:
                msg+="from the local database"
            else:
                msg+="from GitHub API"
            self.logger.info(msg)

            """
            TODO: Check now the freshnes of each repository
            If the repository is fresh and the force flag has not been specified, we ignore the repository to explore.
            For now, we just add all repositories of this organisation to the list of repositories to explore.
            """
            # Append the repositories obtained to the list of repositories to explore
            self.repos_to_explore += org_repos

        return len(self.repos_to_explore)

    def _prepare_repositories_scan(self) -> int:
        """
        Prepare the list of repositories to analyse from the list of repositories provided in the arguments.
        If the repository was recently explored (less than the fresh number of hours) and the force flag was not specified, the repository is ignored
        """
        download_from_gh=False
        # Get the list of organisation names and repositories with their updated status
        explored_repositories_updated=self._get_explored_repositories()

        for target_repo_name in self.target_repository_names:
            repository_is_fresh=None
            # If the repository is currently in the database, check if it's fresh 
            if target_repo_name.casefold() in explored_repositories_updated:
                repository_is_fresh=self._is_date_fresh(explored_repositories_updated[target_repo_name.casefold()])

            # Decide wether to download the data from 
            # User specified force download
            if self.force:
                download_from_gh=True
            # User did not specify force download but the repository data is not fresh
            elif not repository_is_fresh:
                download_from_gh=True
            # The user did not specify force and the data of the database is fresh
            else:
                download_from_gh=False

            # Download from GitHub or use the local cache of the repositories
            repository=None
            if download_from_gh:
                repository = self._get_repository_data_online(target_repo_name)
            # Use the local cache of the repository data
            else:
                repository = self._get_repository_data_from_database(target_repo_name)

            # Print logging message
            org_header_msg = f"= ⛏️ Repository #{target_repo_name} ⛏️ ="
            msg="= 💾 Present in the local database cache 💾 ="
            if download_from_gh:
                msg="= 📡 Retrieved from GitHub API 📡 ="
            self.logger.info("=" * len(org_header_msg))
            self.logger.info(org_header_msg)
            self.logger.info(msg)
            self.logger.info("=" * len(org_header_msg))

            # Append to the list of repository objects to explore
            if repository is not None: 
                self.repos_to_explore.append(repository) 

        return len(self.repos_to_explore)
            

    def scan(self):
        """Scan the repositories for dependencies and identify potential hijackable ones"""
        # Get the organisations
        item_name = "Unknown"
        item_len = 0
        if self.domain_names is not None and len(self.domain_names)>0:
            item_name = "domains"
            item_len = len(self.domain_names)
        elif self.target_organisation_names is not None and len(self.target_organisation_names)>0:
            item_name = "organisations"
            item_len = len(self.target_organisation_names)
        elif self.target_repository_names is not None and len(self.target_repository_names)>0:
            item_name = "repositories"
            item_len = len(self.target_repository_names)


        # Notify the start of the scan via Discord
        discord_msg = f"Starting scan of {item_len} {item_name} at {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        self.bell.ping(msg=discord_msg, title="🎬 Starting scan 🎬")

        target_orgs_n = len(self.target_organisation_names) or 0
        if self.target_organisation_names is not None and  target_orgs_n > 0:
            # Search repos of each organisation
            self.logger.info(
                "⬇️ Pulling repositories information from a list of organisations names or domains provided ⬇️"
            )
            self._prepare_organisations_scan()
        else:
            self.logger.info(
                "Pulling repositories information from the list of repositories provided"
            )
            self._prepare_repositories_scan()

        # Notify the number of repositories we are going to explore via Discord    
        self.bell.ping(
            f"Found {len(self.repos_to_explore)} repositories to explore from the list of {item_name}",
            title="🔍 Repositories to explore 🔍",
        )

        # Now, scan all the repositories
        self.scan_repositories()

        # Notify about the scan is finished
        discord_msg = f"Finished scan of {len(self.repos_to_explore)} repositories at {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        self.bell.ping(msg=discord_msg, title="🏁 Scan finished 🏁")

    def get_scan_progress(self) -> dict:
        """Return the current progress of the repository scan."""
        total_repos = len(self.repos_to_explore)
        if total_repos == 0:
            return {"current": 0, "total": 0, "percentage": 0}

        percentage = int((self.current_repo_index / total_repos) * 100)
        return {"current": self.current_repo_index, "total": total_repos, "percentage": percentage}
