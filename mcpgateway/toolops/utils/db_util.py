from sqlalchemy.orm import Session
from mcpgateway.db import ToolOpsTestCases as TestCaseRecord

from mcpgateway.services.logging_service import LoggingService
logging_service = LoggingService()
logger = logging_service.get_logger(__name__)

def populate_testcases_table(tool_id,test_cases,run_status,db: Session):
    tool_record = db.query(TestCaseRecord).filter_by(tool_id=tool_id).first()
    if not tool_record:
        test_case_record = TestCaseRecord(tool_id= tool_id,test_cases= test_cases,run_status = run_status)
        # Add to DB
        db.add(test_case_record)
        db.commit()
        db.refresh(test_case_record)
        logger.info("Added tool test case record with empty test cases for tool "+str(tool_id)+" with status "+str(run_status))
    #elif tool_record and test_cases != [] and run_status == 'completed':
    elif tool_record:
        tool_record.test_cases = test_cases
        tool_record.run_status = run_status
        db.commit()
        db.refresh(tool_record)
        logger.info("Updated tool record in table with test cases for tool "+str(tool_id)+" with status "+str(run_status))
    

def query_testcases_table(tool_id,db: Session):
    tool_record = db.query(TestCaseRecord).filter_by(tool_id=tool_id).first()
    logger.info("Tool record obtained from table for tool - "+str(tool_id))
    return tool_record
