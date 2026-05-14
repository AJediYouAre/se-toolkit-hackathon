from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        from_attributes = True


class RecipeCreate(BaseModel):
    title: str
    ingredients: str
    instructions: str
    image_url: Optional[str] = None


class RecipeUpdate(BaseModel):
    title: Optional[str] = None
    ingredients: Optional[str] = None
    instructions: Optional[str] = None
    image_url: Optional[str] = None


class RecipeOut(BaseModel):
    id: int
    title: str
    ingredients: str
    instructions: str
    image_url: Optional[str] = None
    created_at: datetime
    user_id: int

    class Config:
        from_attributes = True
