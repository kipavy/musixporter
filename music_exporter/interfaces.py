import abc

class InputSource(abc.ABC):
    """Abstract base class for any music service input."""
    
    @abc.abstractmethod
    def authenticate(self):
        """Handle login and session setup."""
        pass

    @abc.abstractmethod
    def fetch_data(self) -> dict:
        """Retrieve data and return a standardized internal dictionary."""
        pass

class OutputFormatter(abc.ABC):
    """Abstract base class for any file format output."""
    
    @abc.abstractmethod
    def save(self, data: dict, filename: str):
        """Process data and save to file."""
        pass