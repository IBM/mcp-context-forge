import os
import redis
import pickle

redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))

from mcpgateway.services.logging_service import LoggingService
# Initialize logging service first
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)


class CacheTTLDict(dict):
    def __init__(self, ttl):
        self.cache_ttl = ttl
        self.cache = redis.Redis(host=redis_host, port=redis_port)
        logger.info(f"Cache Initialization: {self.cache}")

    def update_cache(self, key, value):
        serialized_obj = pickle.dumps(value)
        logger.info(f"Update cache in cache: {key} {serialized_obj}")
        self.cache.set(key,serialized_obj)
        self.cache.expire(key,60)
        logger.info(f"Cache updated: {self.cache}")

    def retrieve_cache(self, key):
        value = self.cache.get(key)
        if value:
            retrieved_obj = pickle.loads(value)
        logger.info(f"Cache retrieval for id: {key} with value: {retrieved_obj}")
        return retrieved_obj
    
    def delete_cache(self):
        self.cache.flushdb()   
        self.cache.flushall() 

