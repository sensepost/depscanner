from bson import ObjectId
from datetime import datetime

class Package:
    """Package model"""

    def __init__(
        self,
        name: str = "Unknown",
        present: bool = None,
        scope: str = None,
        scope_present: bool = None,
        url: str = "Unknown",
        registry: str = "Unknown",
        language: str = "Unknown",
        metadata: dict = None,
        response_code: int = None,
        scope_response_code: int = None,
        updated: datetime = None,
        _id: ObjectId = None
    ):
        self._id = _id or ObjectId()  # Generate an ObjectId if not provided
        self.name = name
        self.url = url
        self.present = present  # This package is present on the registry
        self.scope = scope
        self.scope_present = scope_present # This package scope (npmjs) exists in the registry
        self.registry = registry
        self.language = language
        self.metadata = metadata
        self.scope_response_code = scope_response_code
        self.response_code = response_code
        self.updated =updated or datetime.now()
    
    def to_dict(self) -> dict:
        """Converts the object into a MongoDB-compatible dictionary."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict):
        """Creates a Package object from a dictionary."""
        if "_id" in data and isinstance(data["_id"], str):
            data["_id"] = ObjectId(data["_id"])  # Convert string to ObjectId
        return cls(**data)

