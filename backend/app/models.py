from sqlalchemy import Column, Integer, String, BigInteger
from .db import Base

class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)

    external_source = Column(String, nullable=False, default="football-data")
    external_id = Column(BigInteger, nullable=False)

    competition = Column(String, nullable=False)
    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)

    utc_date = Column(String, nullable=False)
    date = Column(String, nullable=False)

    status = Column(String, nullable=False)
    home_goals = Column(Integer, nullable=True)
    away_goals = Column(Integer, nullable=True)
    season = Column(Integer, nullable=True)

class MatchContext(Base):
    __tablename__ = "match_context"

    match_id = Column(Integer, primary_key=True, index=True)

    competition = Column(String, nullable=False)
    season = Column(Integer, nullable=False)
    date = Column(String, nullable=False)

    home_team = Column(String, nullable=False)
    away_team = Column(String, nullable=False)

    home_rank_before = Column(Integer, nullable=False)
    away_rank_before = Column(Integer, nullable=False)

    total_teams = Column(Integer, nullable=False)
