from toolops.toolops_logger import setup_logger
from toolops.utils.llm_util import check_llm_env_vars
import logging
logger = logging.getLogger('toolops')
logger.info('Initialised toolops SDK successfully', extra={'details': 'None'})
#logger.info('Checking environment variable configurations', extra={'details': 'None'})
#check_llm_env_vars()
