from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from pymysql.constants import CLIENT
from dotenv import load_dotenv
import os

load_dotenv()

DBHOST = os.getenv("DBHOST", "localhost")
DBPORT = int(os.getenv("DBPORT", 3306))
DBUSER = os.getenv("DBUSER", "root")
DBPASSWORD = os.getenv("DBPASSWORD", "")
DBNAME = os.getenv("DBNAME", "vehicle_diagnostics")

DATABASE_URL = f"mysql+pymysql://{DBUSER}:{DBPASSWORD}@{DBHOST}:{DBPORT}/{DBNAME}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"client_flag": CLIENT.MULTI_STATEMENTS},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------
# Initialize Tables
# -------------------
def init_db():
    with engine.begin() as conn:
        # Chat messages table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_messages(
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL,
            text TEXT NOT NULL,
            sources TEXT,
            user_type ENUM('guest','user') NOT NULL DEFAULT 'guest',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """))

        # Users table
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users(
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role ENUM('Car Owner','Mechanic','Admin') NOT NULL DEFAULT 'Car Owner',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """))

        sender_exists = conn.execute(
            text("""
            SELECT COUNT(*) AS c
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA=:schema AND TABLE_NAME='chat_messages' AND COLUMN_NAME='sender_name'
            """),
            {"schema": DBNAME},
        ).scalar()
        if not sender_exists:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN sender_name VARCHAR(120) NULL"))
        recipient_exists = conn.execute(
            text("""
            SELECT COUNT(*) AS c
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA=:schema AND TABLE_NAME='chat_messages' AND COLUMN_NAME='recipient'
            """),
            {"schema": DBNAME},
        ).scalar()
        if not recipient_exists:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN recipient VARCHAR(120) NULL"))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS guest_sessions(
            id INT AUTO_INCREMENT PRIMARY KEY,
            session_id VARCHAR(100) UNIQUE NOT NULL,
            expires_at DATETIME NOT NULL
        );
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS conversations(
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            title VARCHAR(200) NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """))

        col_exists = conn.execute(
            text("""
            SELECT COUNT(*) AS c
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA=:schema AND TABLE_NAME='chat_messages' AND COLUMN_NAME='conversation_id'
            """),
            {"schema": DBNAME},
        ).scalar()
        if not col_exists:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN conversation_id INT NULL"))
        fk_exists = conn.execute(
            text("""
            SELECT COUNT(*) AS c
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA=:schema AND TABLE_NAME='chat_messages' AND CONSTRAINT_NAME='fk_chat_conversation' AND CONSTRAINT_TYPE='FOREIGN KEY'
            """),
            {"schema": DBNAME},
        ).scalar()
        if not fk_exists:
            conn.execute(text("ALTER TABLE chat_messages ADD CONSTRAINT fk_chat_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id)"))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS vehicles(
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            make VARCHAR(100),
            model VARCHAR(100),
            year INT,
            vin VARCHAR(32) UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS diagnostic_records(
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            vehicle_id INT NULL,
            dtc_code VARCHAR(20),
            status ENUM('Normal','Warning','Critical') DEFAULT 'Normal',
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
        );
        """))

init_db()
