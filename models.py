# /IMS-backend/models.py
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime
from bson import ObjectId

# Helper to handle MongoDB ObjectId
class PyObjectId(str):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return str(v)

# Activity Model
class Activity(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    action: str
    entityType: Literal["order", "product", "supplier", "user"]
    entityId: str
    details: str
    userId: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        from_attributes = True

# Feedback Model
class Feedback(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    userId: str
    productId: str
    comment: str = Field(..., min_length=1, max_length=500)
    rating: int = Field(..., ge=1, le=5)
    createdAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        from_attributes = True

# Order Item Submodel
class OrderItem(BaseModel):
    productId: str
    quantity: int = Field(..., gt=0)
    price: float = Field(..., gt=0)

# Order Model
class Order(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    customerId: str
    items: List[OrderItem]
    totalAmount: float = Field(..., gt=0)
    status: Literal["processing", "shipped", "completed", "cancelled"] = "processing"
    orderDate: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        from_attributes = True

# Payment Model
class Payment(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    orderID: PyObjectId
    amount: float = Field(..., ge=0)
    status: Literal["pending", "completed", "failed"] = "pending"
    paymentMethod: Literal["credit_card", "paypal", "bank_transfer"]
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        from_attributes = True


class Product(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    name: str
    price: float = Field(..., gt=0)
    quantity: int = Field(..., ge=0)
    imageUrl: Optional[str] = None
    category: Optional[str] = None
    supplierId: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: Optional[datetime] = None
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        from_attributes = True

class Supplier(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    name: str
    contactEmail: EmailStr
    contactPhone: Optional[str] = None
    address: Optional[str] = None
    productsSupplied: Optional[List[str]] = None
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        from_attributes = True

class User(BaseModel):
    id: Optional[PyObjectId] = Field(default_factory=lambda: str(ObjectId()), alias="_id")
    name: str
    email: EmailStr
    password: str
    role: Literal["customer", "admin"] = "customer"
    lowStockThreshold: int = Field(default=10, ge=0)
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    class Config:
        arbitrary_types_allowed = True
        json_encoders = {ObjectId: str}
        from_attributes = True
# Login Request Model
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)

# Register Request Model
class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: Optional[Literal["customer", "admin"]] = "customer"