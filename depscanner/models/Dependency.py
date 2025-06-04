from bson import ObjectId
from datetime import datetime

class Dependency:
    """This model represents a dependency between a github repository and a specific package/library"""

    def __init__(
        self,
        repo_name: str = None,
        repo_id: ObjectId = None,
        dependency_file: str = None,
        semver: str = None,
        package_name: str = None,
        package_id: ObjectId = None,
        updated: datetime = None,
        _id: ObjectId = None,
    ):
        self._id = _id or ObjectId()  # Generate an ObjectId if not provided
        self.repo_name = repo_name
        self.repo_id = repo_id
        self.package_id = package_id
        self.package_name = package_name
        self.dependency_file = dependency_file
        self.semver = semver
        self.updated = updated or datetime.now().isoformat()
    
    def to_dict(self) -> dict:
        """Converts the Dependency object into a MongoDB-compatible dictionary."""
        return {
            "_id": self._id,
            "repo_name": self.repo_name,
            "repo_id": self.repo_id,
            "package_name": self.package_name,
            "package_id": self.package_id,
            "dependency_file": self.dependency_file,
            "semver": self.semver,
            "updated": self.updated
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Creates a Dependency object from a dictionary."""
        # Convert IDs strings in ObjectIds objects
        if "_id" in data and isinstance(data["_id"], str):
            data["_id"] = ObjectId(data["_id"])  

        if "package_id" in data and isinstance(data["package_id"], str):
            data["package_id"] = ObjectId(data["package_id"]) 
        
        if "repo_id" in data and isinstance(data["repo_id"], str):
            data["repo_id"] = ObjectId(data["repo_id"]) 

        return cls(
            _id=data["_id"],
            repo_name=data["repo_name"],
            repo_id=data["repo_id"],
            package_id=data["package_id"],  
            package_name=data["package_name"],  
            dependency_file=data["dependency_file"],
            semver=data["semver"],
            updated = data["updated"]
        )
