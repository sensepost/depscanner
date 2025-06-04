import logging
from pymongo import MongoClient, UpdateOne
from pymongo.collection import Collection, Cursor
from pymongo.errors import ConnectionFailure, DuplicateKeyError
from datetime import datetime

from depscanner.models.Package import Package
from depscanner.models.Dependency import Dependency
from depscanner.models.Scope import Scope

from bson import ObjectId

logger = logging.getLogger(__name__)


def logging_setup(arguments):
    logging.basicConfig(
        level=getattr(logging, arguments.level),
        format="%(asctime)s - %(levelname)s - %(message)s",
        filename="mongomanager.log",
    )
    # Create console handler
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, arguments.level))
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(console)


class MongoManager:
    """This class is in charge of interacting with the Mongo database"""

    def __init__(
        self, host: str, port: int, database: str, username: str, password: str, logger: logging.Logger = None
    ):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.KEEP_VERSIONS = 30
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.client = self._init_db_client(
            host=host, port=port, username=username, password=password
        )
        self.db = self.client[database]

    def _init_db_client(
        self, host: str, port: int, username: str, password: str
    ) -> MongoClient:
        logger.debug("Opening a connection to the mongo db")
        client = MongoClient(host=host, port=port, username=username, password=password)
        try:
            client.admin.command("ismaster")
        except ConnectionFailure:
            logger.error("Server not available")
            return None
        return client

    def close_database(self):
        """Close connection with the Mongo database"""
        self.client.close()

    def save_company_repos(self, company_repos: dict):
        """Save many repositories entries. Retrieved from GitHub API https://api.github.com/orgs/{organisation}/repos"""
        # Check if the repository exists by name, if it exists, it's an upsert command instead of an insert
        # Add timestamp to the record
        operations = []
        for repo in company_repos:
            repo["updated"] = datetime.now()
            operations.append(
                UpdateOne(
                    {"name": repo["name"]},  # Query condition (match by "name")
                    {"$set": repo},  # Update or insert the repository data
                    upsert=True,  # Insert if not exists, otherwise update
                )
            )

        if operations:
            self.db.repositories.bulk_write(operations)

    def save_single_repository(self, repo: dict):
        """This saves a single repository information. Retrieved from GH API https://api.github.com/repos/{repo_name}"""
        repo["updated"] = datetime.now()
        self.db.repositories.update_one(
            {"name": repo["name"]}, {"$set": repo}, upsert=True
        )

    def _reduce_package_size(self, package_dict: dict) -> dict:
        """
        This function reduces the package size to keep only the last KEEP_VERSIONS versions. 
        This helps reducing storage requirements and prevents errors storing large documents in Mongo.
        There are packages with thousands of versions
        """
        # If the version info exists and is larger than our limit, chop the excesive number of versions
        if ('metadata' in package_dict 
            and type(package_dict['metadata']) == dict 
            and 'versions' in package_dict['metadata'].keys() 
            and len(package_dict['metadata']['versions'])>self.KEEP_VERSIONS
            ):
            versions_dict = package_dict['metadata']['versions']
            # Get sorted version keys
            version_keys = sorted(versions_dict.keys())  # Assuming versions are sortable strings like "1.0.0"
            
            # Keep only the last N versions
            last_versions = version_keys[-self.KEEP_VERSIONS:]
            
            # Create a new dictionary with only the last N versions
            package_dict['metadata']['versions'] = {k: versions_dict[k] for k in last_versions}
        return package_dict

    def save_package(self, package: Package, allow_duplicates: bool = False) -> Collection:
        """
        Save a package information retrieved from its registry API.
        The format of the data is different for each registry, so we wrap the information within a wrapper object.
        It only contains the package name and registry name and the raw json data retrieved from the registry API.
        """
        pd = package.to_dict()
        pd=self._reduce_package_size(package_dict=pd)
        return self.db.packages.insert_one(pd)

    def update_package(self, package: Package):
        """Update a package entry"""
        package_without_id = package.to_dict()
        package_without_id=self._reduce_package_size(package_dict=package_without_id)
        del package_without_id["_id"]
        return self.db.packages.update_one(
            {"name": package.name, "registry": package.registry},
            {
                "$set": package_without_id
            }
        )

    def save_repository_dependency(
        self, dependency: Dependency
    ) -> Collection:
        """This saves the dependency and the information is extracted from a package object"""
        res = None
        try:
            res = self.db.dependencies.insert_one(dependency.to_dict())
        except DuplicateKeyError:
            self.logger.debug(f"Duplicate key when inserting dependency: {dependency.to_dict()}")
        return res

    def get_explored_orgs(self, name: str=None, number_repos: int=None) -> Collection:
        """Save an entry in the organisations collection with the number of repositories it has on GitHub"""
        filter={}
        if name:
            filter["name"]=name
        if name:
            filter["number_repos"]=number_repos
        return self.db.explored_orgs.find(filter,{"name": 1, "number_repos": 1, "updated": 1})

    def save_or_update_explored_org(self, name: str, number_repos: int) -> Collection:
        """Save an entry in the organisations collection with the number of repositories it has on GitHub"""
        return self.db.explored_orgs.update_one(
            {"name": name},
            {
                "$set": {
                    'number_repos': number_repos, 
                    'updated':  datetime.now()
                }
            },
            upsert=True
        )
        # self.db.explored_orgs.insert_one({"name": name, "number_repos": number_repos, "updated": datetime.now()})
    
    def update_explored_orgs(self, name: str, number_repos: int) -> Collection:
        """Save an entry in the organisations collection with the number of repositories it has on GitHub"""
        return self.db.explored_orgs.update_one(
            {"name": name},
            {
                "$set": {
                    'number_repos': number_repos, 
                    'updated':  datetime.now()
                }
            },
        )

    def get_scopes(self, _id: ObjectId=None, name: str =None) -> Collection:
        """This gets an scope object from the database"""
        filter={}
        if _id:
            filter["_id"]=_id
        if name:
            filter["name"]=name

        return self.db.scopes.find(filter)

    def save_scope(self, scope: Scope) -> Collection:
        """This saves an scope object"""
        try:
            res = self.db.scopes.insert_one(scope.to_dict())
            return res
        except DuplicateKeyError: 
            self.logger.debug(f"Attempted to save scope '{scope.name}' and it was a duplicate")
        return None

    def update_scope(self, scope: Scope) -> Collection:
        """This updates an scope object"""
        scope_without_id = scope.to_dict()
        del scope_without_id["_id"]
        return self.db.scopes.update_one(
            {"name": scope.name},
            {
                "$set": scope_without_id
            },
        )

    def update_repository_dependency(
        self, dependency: Dependency
    ) -> Collection:
        """Update a dependency document"""
        dependency_without_id = dependency.to_dict()
        del dependency_without_id["_id"]
        return self.db.dependencies.update_one(
            {
                "repo_name": dependency.repo_name, 
                "package_name": dependency.package_name, 
                "dependency_file": dependency.dependency_file,
                "semver": dependency.semver,
                "repo_id": dependency.repo_id
            },
            {
                "$set": {
                    "package_id": dependency.package_id,
                    "updated": datetime.now()
                }
            }
        )

    def get_company_repos(self, company_name: str):
        """Return all repositories of this company"""
        repositories = self.db.repositories.find({"owner.login": company_name})
        if repositories:
            repositories.sort("timestamp")

        return repositories
    
    def get_organisation_names(self)->list[str]:
        """Return all repositories of this company"""
        organisation_names = set()
        for org in list(self.db.repositories.find({},{"_id":0, "owner.login": 1})):
            organisation_names.add(org['owner']['login'])

        return organisation_names

    def get_repository_updated(self, _id: ObjectId=None, repo_name: str = None, organisation: str = None):
        """Return a repository if its in the database"""
        filter={}
        if _id:
            filter["_id"]=_id
        if repo_name:
            filter["full_name"]=repo_name
        if organisation:
            filter["owner.login"]=organisation
        projection = {"full_name": 1, "updated": 1}

        return self.db.repositories.find(filter,projection).sort({'updated': -1})

    def get_repositories(self, _id: ObjectId=None, repo_name: str = None, organisation: str = None):
        """Return a repository if its in the database"""
        filter={}
        if _id:
            filter["_id"]=_id
        if repo_name:
            filter["full_name"]=repo_name
        if organisation:
            filter["owner.login"]=organisation

        return self.db.repositories.find(filter)

    def get_packages(
        self,
        _id: ObjectId = None,
        package_name: str = None,
        package_version: str = None,
        registry: str = None,
        language: str = None,
        present: bool = None,
        response_code: int = None
    ) -> Cursor:
        """Return the package details"""

        # Add conditional search filters if specified in the arguments
        search_filter = {}
        if _id:
            search_filter["_id"] = _id
        if package_name:
            search_filter["name"] = package_name
        if package_version:
            search_filter["version"] = package_version
        if registry:
            search_filter["registry"] = registry
        if language:
            search_filter["language"] = language
        if present is not None:
            search_filter["present"] = present
        if response_code:
            search_filter["response_code"] = response_code

        return self.db.packages.find(search_filter).sort("timestamp")

    def get_dependencies(self, repo_id: ObjectId=None, repo_name: str=None, package_id: ObjectId=None, package_name: str=None):
        """Return a dependency entry between a repository name and a package"""
        filter = {}
        if repo_name:
            filter["repo_id"] = repo_id
        if repo_name:
            filter["repo_name"] = repo_name
        if package_name:
            filter["package_name"] = package_name
        if package_id:
            filter["package_id"] = package_id

        return self.db.dependencies.find(filter)

