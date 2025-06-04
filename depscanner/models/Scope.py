from bson import ObjectId
from datetime import datetime

class Scope:
    """Scope model"""

    def __init__(
        self,
        _id: ObjectId = None,
        name: str = None,
        present: bool = None,
        response_code: int = None,
        updated: datetime = None,
    ):
        self._id = _id or ObjectId()  # Generate an ObjectId if not provided
        self.name = name
        self.present = present
        self.response_code = response_code
        self.updated = updated or datetime.now().isoformat()
    
    def to_dict(self) -> dict:
        """Converts the object into a MongoDB-compatible dictionary."""
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict):
        """Creates a Package object from a dictionary."""
        if "_id" in data and isinstance(data["_id"], str):
            data["_id"] = ObjectId(data["_id"])  # Convert string to ObjectId
        return cls(**data)
