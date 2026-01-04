import abc

class InputSource(abc.ABC):
    @abc.abstractmethod
    def authenticate(self): pass
    @abc.abstractmethod
    def fetch_data(self) -> dict: pass

class OutputFormatter(abc.ABC):
    @abc.abstractmethod
    def save(self, data: dict, filename: str): pass

class IdConverter(abc.ABC):
    """Abstract base class for mapping IDs from one service to another."""
    @abc.abstractmethod
    def convert(self, data: dict) -> dict:
        """Takes generic data, performs lookups, returns data with target IDs."""
        pass