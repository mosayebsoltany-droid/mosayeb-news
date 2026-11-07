from argparse import ArgumentParser
from getpass import getpass

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.auth import passwords
from app.database import Base, SessionLocal, engine
from app.models import User, UserRole
from app.schemas import UserCreate


def main():
    parser = ArgumentParser(description="Create a broker account")
    parser.add_argument("username")
    parser.add_argument("--role", choices=[role.value for role in UserRole], default="broker")
    args = parser.parse_args()
    password = getpass("Password (12–128 characters): ")
    if password != getpass("Confirm password: "):
        parser.exit(1, "Passwords do not match\n")
    try:
        data = UserCreate(username=args.username, password=password)
    except ValidationError:
        parser.exit(1, "Invalid username or password length\n")
    if engine.dialect.name == "sqlite" and get_settings().auto_create_tables:
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(User(username=data.username, hashed_password=passwords.hash(data.password), role=UserRole(args.role)))
        try:
            db.commit()
        except IntegrityError:
            parser.exit(1, "Account already exists\n")
    print("Broker account created")


if __name__ == "__main__":
    main()
