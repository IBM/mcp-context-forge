# -*- coding: utf-8 -*-
"""CLI for verifying load test data integrity.

Usage:
    python -m tests.load.verify --profile production
    python -m tests.load.verify --checks foreign_keys,uniqueness
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mcpgateway.config import settings

from .utils.validation import DataValidator


# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_database_session():
    """Create database session.

    Returns:
        SQLAlchemy session
    """
    engine = create_engine(settings.database_url, echo=False)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Verify load test data integrity in ContextForge database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--profile",
        type=str,
        choices=["small", "medium", "large", "production", "massive"],
        help="Profile to verify"
    )

    parser.add_argument(
        "--checks",
        type=str,
        help="Comma-separated list of checks (foreign_keys,uniqueness,required_fields,email_formats)"
    )

    parser.add_argument(
        "--output",
        type=str,
        help="Output report path (JSON)"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create database session
    db = create_database_session()

    try:
        logger.info("Starting data verification...")

        validator = DataValidator(db, logger)

        # Run validation
        results = validator.validate_all()

        # Get table counts
        table_counts = validator.get_table_counts()
        results["table_counts"] = table_counts

        # Print results
        print("\n" + "="*80)
        print("Verification Results")
        print("="*80)

        for check_name, check_result in results.items():
            if check_name in ["all_passed", "table_counts"]:
                continue

            status = "✓ PASS" if check_result.get("passed", False) else "✗ FAIL"
            print(f"\n{check_name}: {status}")

            if not check_result.get("passed", False):
                if "details" in check_result:
                    for detail in check_result["details"][:5]:  # Show first 5
                        print(f"  - {detail}")
                if "error" in check_result:
                    print(f"  Error: {check_result['error']}")

        print("\n" + "-"*80)
        print("Table Counts:")
        print("-"*80)
        for table, count in sorted(table_counts.items()):
            print(f"  {table:40s} {count:>15,}")

        print("\n" + "="*80)
        overall = "✓ ALL CHECKS PASSED" if results.get("all_passed", False) else "✗ SOME CHECKS FAILED"
        print(f"Overall: {overall}")
        print("="*80)

        # Save report
        if args.output:
            output_file = Path(args.output)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2, default=str)

            logger.info(f"Report saved to: {output_file}")

        # Exit code
        sys.exit(0 if results.get("all_passed", False) else 1)

    except Exception as e:
        logger.error(f"Verification failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
