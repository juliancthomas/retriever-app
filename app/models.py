from app.db.database import Base
from sqlalchemy import Column, Integer, String

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    name = Column(String)