from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from career_radar.models import Opportunity


def test_mysql_description_and_unique_key_contract():
    ddl = str(CreateTable(Opportunity.__table__).compile(dialect=mysql.dialect()))
    assert "MEDIUMTEXT" in ddl
    assert "uq_opportunity_source_external" in ddl
    assert "utf8mb4_bin" in ddl
