from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, create_engine, ForeignKey, func
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///bot.db"

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)              # Telegram user_id
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False)        # sbloccato con parola-chiave
    total_used = Column(Integer, default=0)             # risposte totali consumate
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

class MessageLog(Base):
    __tablename__ = "message_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    text = Column(Text, nullable=True)
    kind = Column(String, default="reply")             # reply / blocked / error
    meta = Column(Text, nullable=True)                 # JSON string (optional)
    created_at = Column(DateTime, server_default=func.now())
