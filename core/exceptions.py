class AgentError(Exception):
    pass

class LLMError(AgentError):
    pass

class ScrapingError(AgentError):
    pass

class SearchAPIError(AgentError):
    pass

class StorageError(AgentError):
    pass
