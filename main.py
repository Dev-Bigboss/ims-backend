from datetime import datetime
from bson import ObjectId
from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File
from pymongo import MongoClient
from typing import List, Literal, Optional
from dotenv import load_dotenv
import os
import bcrypt
import jwt
from models import Activity, CartItem, Feedback, Order, Payment, Product, Supplier, User, LoginRequest, RegisterRequest, OrderItem
from auth import with_auth
import aiofiles
from pydantic import EmailStr, BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
JWT_SECRET = os.getenv("JWT_SECRET")

app = FastAPI()

# CORS configuration
origins = [
    "http://localhost:3000",  # Next.js frontend
    # Add production URLs later, e.g., "https://yourdomain.com"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/uploads", StaticFiles(directory="public/uploads"), name="uploads")

# MongoDB Connection
client = None
def get_db():
    global client
    if not MONGODB_URI:
        raise HTTPException(status_code=500, detail="Server configuration error")
    if not client:
        client = MongoClient(MONGODB_URI)
    return client["inventoryhub"]

class ProductCreate(BaseModel):
    name: str
    price: float
    quantity: int
    imageUrl: Optional[str] = None
    supplierId: str
    
class ProductUpdate(BaseModel):
    name: str
    price: float
    quantity: int
    imageUrl: Optional[str] = None
    supplierId: str

@app.put("/api/products/{id}", response_model=dict)
async def update_product(id: str, product: ProductUpdate, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    product_data = product.dict(exclude_unset=True)  # Only update provided fields
    result = db["products"].update_one({"_id": ObjectId(id)}, {"$set": product_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    
    updated_product = db["products"].find_one({"_id": ObjectId(id)})
    return {"data": {"id": str(updated_product["_id"]), **updated_product}}

# --- Auth Endpoints ---
@app.post("/api/auth/login", response_model=dict)
async def login(login: LoginRequest, db=Depends(get_db)):
    users = db["users"]
    user = users.find_one({"email": login.email})
    if not user or not bcrypt.checkpw(login.password.encode("utf-8"), user["password"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server configuration error")
    
    token = jwt.encode({"userId": str(user["_id"]), "role": user["role"]}, JWT_SECRET, algorithm="HS256")
    return {"token": token}

@app.post("/api/auth/register", response_model=dict)
async def register(register: RegisterRequest, db=Depends(get_db)):
    users = db["users"]
    if users.find_one({"email": register.email}):
        raise HTTPException(status_code=409, detail="User already exists")
    
    user_role = "customer" if register.role == "admin" else register.role
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(register.password.encode("utf-8"), salt).decode("utf-8")
    
    user_data = {
        "name": register.name,
        "email": register.email,
        "password": hashed_password,
        "role": user_role,
        "lowStockThreshold": 10,
        "createdAt": datetime.utcnow(),
        "favorites": [],
        "cartItems": []
    }
    result = users.insert_one(user_data)
    
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server configuration error")
    
    token = jwt.encode({"userId": str(result.inserted_id), "role": user_role}, JWT_SECRET, algorithm="HS256")
    return {"token": token}

# --- Activity Endpoints ---
@app.get("/api/activities", response_model=dict)
async def get_activities(page: int = 1, limit: int = 10, entityType: Optional[str] = None, auth=Depends(with_auth), db=Depends(get_db)):
    activities_coll = db["activities"]
    skip = (page - 1) * limit
    query = {"entityType": entityType} if entityType else {}
    activities = list(activities_coll.find(query).skip(skip).limit(limit).sort("createdAt", -1))
    total = activities_coll.count_documents(query)
    data = [{"id": str(act["_id"]), **act} for act in activities]
    return {"data": data, "total": total, "page": page, "limit": limit}

@app.post("/api/activities", response_model=dict)
async def create_activity(activity: Activity, auth=Depends(with_auth), db=Depends(get_db)):
    activities_coll = db["activities"]
    activity_data = activity.dict(exclude={"id"})
    result = activities_coll.insert_one(activity_data)
    return {"data": {"id": str(result.inserted_id), **activity_data}}

# --- Features Endpoint ---
@app.get("/api/features", response_model=List[dict])
async def get_features():
    features = [
        {"icon": "FaShoppingCart", "title": "Seamless Shopping", "desc": "Browse, cart, and checkout in Naira—fast and intuitive."},
        {"icon": "FaCogs", "title": "Smart Admin Tools", "desc": "Manage stock, orders, and suppliers with ease."},
        {"icon": "FaChartLine", "title": "Real-Time Analytics", "desc": "Gain insights with live sales and stock data."},
    ]
    return features

# --- Feedback Endpoints ---
@app.get("/api/feedback", response_model=dict)
async def get_feedback(page: int = 1, limit: int = 10, productId: Optional[str] = None, auth=Depends(with_auth), db=Depends(get_db)):
    feedback_coll = db["feedback"]
    user = auth  # from with_auth
    skip = (page - 1) * limit

    if productId:
        feedback = list(feedback_coll.find({"productId": productId}).sort("createdAt", -1))
        data = [{"id": str(f["_id"]), **f} for f in feedback]
        return {"data": data}
    
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    feedback = list(feedback_coll.find().skip(skip).limit(limit).sort("createdAt", -1))
    total = feedback_coll.count_documents({})
    data = [{"id": str(f["_id"]), **f} for f in feedback]
    return {"data": data, "total": total, "page": page, "limit": limit}

class Feedback(BaseModel):
    productId: str
    comment: str
    rating: int
    id: Optional[str] = None  # Excluded in POST
    userId: Optional[str] = None  # Added server-side
    createdAt: Optional[str] = None  # Added server-side

@app.post("/api/feedback", response_model=dict)
async def create_feedback(feedback: Feedback, auth=Depends(with_auth), db=Depends(get_db)):
    feedback_coll = db["feedback"]
    user = auth
    feedback_data = feedback.dict(exclude={"id"})
    feedback_data["userId"] = user["userId"]
    feedback_data["createdAt"] = datetime.utcnow().isoformat()  # Add this
    result = feedback_coll.insert_one(feedback_data)
    return {"data": {"id": str(result.inserted_id), **feedback_data}}

# --- Order History Endpoint ---
@app.get("/api/order-history", response_model=dict)
async def get_order_history(id: Optional[str] = None, page: int = 1, limit: int = 10, auth=Depends(with_auth), db=Depends(get_db)):
    orders_coll = db["orders"]
    user = auth
    skip = (page - 1) * limit

    if id:
        order = orders_coll.find_one({"_id": ObjectId(id), "customerId": user["userId"]})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found or not authorized")
        return {"data": {"id": str(order["_id"]), **order}}

    orders = list(orders_coll.find({"customerId": user["userId"]}).skip(skip).limit(limit).sort("orderDate", -1))
    total = orders_coll.count_documents({"customerId": user["userId"]})
    data = [{"id": str(o["_id"]), **o} for o in orders]
    return {"data": data, "total": total, "page": page, "limit": limit}

# --- Orders Endpoints ---
@app.get("/api/orders", response_model=dict)
async def get_orders(page: int = 1, limit: int = 10, auth=Depends(with_auth), db=Depends(get_db)):
    orders_coll = db["orders"]
    skip = (page - 1) * limit
    orders = list(orders_coll.find().skip(skip).limit(limit))
    total = orders_coll.count_documents({})
    data = [{"id": str(o["_id"]), **o} for o in orders]
    return {"data": data, "total": total, "page": page, "limit": limit}

class OrderStatusUpdate(BaseModel):
    status: str

@app.get("/api/orders/{id}", response_model=dict)
async def get_order(id: str, auth=Depends(with_auth), db=Depends(get_db)):
    try:
        order = db["orders"].find_one({"_id": ObjectId(id)})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        order_data = {"id": str(order["_id"]), **order}
        return {"data": order_data}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order ID format")
    
@app.put("/api/orders/{id}/status", response_model=dict)
async def update_order_status(id: str, status_update: OrderStatusUpdate, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    try:
        result = db["orders"].update_one(
            {"_id": ObjectId(id)},
            {"$set": {"status": status_update.status}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Order not found")
        updated_order = db["orders"].find_one({"_id": ObjectId(id)})
        return {"data": {"id": str(updated_order["_id"]), **updated_order}}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order ID format")

@app.post("/api/orders", response_model=dict)
async def create_order(items: List[OrderItem], auth=Depends(with_auth), db=Depends(get_db)):
    orders_coll = db["orders"]
    products_coll = db["products"]
    users_coll = db["users"]
    activities_coll = db["activities"]
    user = auth

    if not items:
        raise HTTPException(status_code=400, detail="Cart items are required")

    order_items = []
    for item in items:
        product = products_coll.find_one({"_id": ObjectId(item.productId)})
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.productId} not found")
        if product["quantity"] < item.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {product['name']}")
        order_items.append({"productId": str(product["_id"]), "quantity": item.quantity, "price": product["price"]})

    total_amount = sum(item["price"] * item["quantity"] for item in order_items)
    order_data = {
        "customerId": user["userId"],
        "items": order_items,
        "totalAmount": total_amount,
        "status": "processing",
        "orderDate": datetime.utcnow()
    }
    result = orders_coll.insert_one(order_data)
    order_id = str(result.inserted_id)

    for item in order_items:
        products_coll.update_one({"_id": ObjectId(item["productId"])}, {"$inc": {"quantity": -item["quantity"]}})

    users_coll.update_one({"_id": ObjectId(user["userId"])}, {"$set": {"cartItems": []}})
    activities_coll.insert_one({
        "action": "Created",
        "entityType": "order",
        "entityId": order_id,
        "details": f"Order #{order_id[-6:]} placed",
        "userId": user["userId"],
        "createdAt": datetime.utcnow()
    })

    return {"data": {"id": order_id, **order_data}}

# --- User Favorites Endpoints ---
@app.get("/api/user/favorites", response_model=dict)
async def get_user_favorites(auth=Depends(with_auth), db=Depends(get_db)):
    users_coll = db["users"]
    user = auth
    user_data = users_coll.find_one({"_id": ObjectId(user["userId"])}, {"favorites": 1})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    return {"favorites": user_data.get("favorites", [])}

@app.put("/api/user/favorites", response_model=dict)
async def update_user_favorites(favorites: List[str], auth=Depends(with_auth), db=Depends(get_db)):
    users_coll = db["users"]
    user = auth
    updated_user = users_coll.find_one_and_update(
        {"_id": ObjectId(user["userId"])},
        {"$set": {"favorites": favorites}},
        return_document=True
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"favorites": updated_user["favorites"]}

# --- User Cart Endpoints ---
@app.get("/api/user/cart", response_model=dict)
async def get_user_cart(auth=Depends(with_auth), db=Depends(get_db)):
    users_coll = db["users"]
    user = auth
    user_data = users_coll.find_one({"_id": ObjectId(user["userId"])}, {"cartItems": 1})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    cart_items = [
        {"productId": item["productId"], "quantity": item["quantity"], "price": item["price"]}
        for item in user_data.get("cartItems", [])
    ]
    return {"cartItems": cart_items}

@app.put("/api/user/cart", response_model=dict)
async def update_user_cart(cartItems: List[CartItem], auth=Depends(with_auth), db=Depends(get_db)):
    users_coll = db["users"]
    user = auth
    cart_data = [item.dict() for item in cartItems]
    updated_user = users_coll.find_one_and_update(
        {"_id": ObjectId(user["userId"])},
        {"$set": {"cartItems": cart_data}},
        return_document=True
    )
    
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"cartItems": updated_user["cartItems"]}

# --- Products Endpoints ---
class ProductResponse(BaseModel):
    id: str
    name: str
    price: float
    quantity: int
    imageUrl: Optional[str] = None
    supplierId: str

class PaginatedProductsResponse(BaseModel):
    data: list[ProductResponse]
    total: int
    page: int
    limit: int

# List of products
@app.get("/api/products", response_model=PaginatedProductsResponse)
async def get_products_list(
    page: int = 1,
    limit: int = 10,
    auth=Depends(with_auth),
    db=Depends(get_db)
):
    products_coll = db["products"]
    skip = (page - 1) * limit
    products = list(products_coll.find().skip(skip).limit(limit))
    total = products_coll.count_documents({})
    data = [{"id": str(p["_id"]), **p} for p in products]
    return {"data": data, "total": total, "page": page, "limit": limit}

# Single product by ID
@app.get("/api/products/{id}", response_model=dict)
async def get_product(
    id: str,
    auth=Depends(with_auth),
    db=Depends(get_db)
):
    products_coll = db["products"]
    try:
        product = products_coll.find_one({"_id": ObjectId(id)})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        product_data = {"id": str(product["_id"]), **product}
        return {"data": product_data}
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid product ID format")
    
@app.delete("/api/products/{id}", response_model=dict)
async def delete_product(id: str, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    result = db["products"].delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"message": "Product deleted successfully"}

@app.post("/api/products", response_model=dict)
async def create_product(product: ProductCreate, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    product_data = product.dict()
    result = db["products"].insert_one(product_data)
    return {"data": {"id": str(result.inserted_id), **product_data}}

@app.post("/api/upload", response_model=dict)
async def upload_file(file: UploadFile = File(...), auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    async with aiofiles.open(f"public/uploads/{file.filename}", "wb") as out_file:
        content = await file.read()
        await out_file.write(content)
    image_url = f"/uploads/{file.filename}"
    return {"imageUrl": image_url}

# --- Report Endpoint ---
@app.get("/api/report", response_model=dict)
async def get_report(days: int = 30, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    products_coll = db["products"]
    orders_coll = db["orders"]
    suppliers_coll = db["suppliers"]

    products = list(products_coll.find())
    cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = cutoff.replace(day=cutoff.day - days)
    orders = list(orders_coll.find({"orderDate": {"$gte": cutoff}}))
    suppliers = list(suppliers_coll.find())

    in_stock = len([p for p in products if p["quantity"] > 10])
    low_stock = len([p for p in products if 0 < p["quantity"] <= 10])
    out_of_stock = len([p for p in products if p["quantity"] == 0])

    revenue_by_day = {}
    for order in orders:
        date = order["orderDate"].strftime("%Y-%m-%d")
        revenue_by_day[date] = revenue_by_day.get(date, 0) + order["totalAmount"]

    product_order_count = {}
    for order in orders:
        for item in order["items"]:
            product_order_count[item["productId"]] = product_order_count.get(item["productId"], 0) + item["quantity"]
    top_products = sorted(product_order_count.items(), key=lambda x: x[1], reverse=True)[:5]
    top_products_data = [
        {"name": products_coll.find_one({"_id": ObjectId(pid)})["name"] if products_coll.find_one({"_id": ObjectId(pid)}) else "Unknown", "count": count}
        for pid, count in top_products
    ]

    supplier_product_count = [
        {"supplierName": s["name"], "productCount": products_coll.count_documents({"supplierId": str(s["_id"])})}
        for s in suppliers
    ]
    supplier_order_volume = []
    for s in suppliers:
        supplier_products = list(products_coll.find({"supplierId": str(s["_id"])}))
        supplier_product_ids = [str(p["_id"]) for p in supplier_products]
        order_count = sum(1 for o in orders if any(item["productId"] in supplier_product_ids for item in o["items"]))
        supplier_order_volume.append({"supplierName": s["name"], "orderCount": order_count})

    return {
        "data": {
            "products": [{"id": str(p["_id"]), **p} for p in products],
            "orders": [{"id": str(o["_id"]), **o} for o in orders],
            "stockLevels": {"inStock": in_stock, "lowStock": low_stock, "outOfStock": out_of_stock},
            "revenueByDay": revenue_by_day,
            "topProducts": top_products_data,
            "supplierProductCount": supplier_product_count,
            "supplierOrderVolume": supplier_order_volume,
        }
    }

@app.post("/api/create-admin", response_model=dict)
async def create_admin(db=Depends(get_db)):
    users_coll = db["users"]
    
    # Check if admin already exists
    existing_admin = users_coll.find_one({"role": "admin"})
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin user already exists")
    
    # Admin user data
    admin_data = {
        "name": "Admin User",
        "email": "admin@admin.com",
        "password": bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8"),
        "role": "admin",
        "lowStockThreshold": 10,
        "createdAt": datetime.utcnow().isoformat(),
        "favorites": [],
        "cartItems": []
    }
    
    result = users_coll.insert_one(admin_data)
    admin_data["id"] = str(result.inserted_id)
    admin_data.pop("_id")
    admin_data.pop("password")  # Don’t return password
    
    return {"data": admin_data, "message": "Admin user created successfully"}
# --- Suppliers Endpoints ---
class Supplier(BaseModel):
    name: str
    contactEmail: EmailStr
    contactPhone: str
    address: Optional[str] = None

# GET /api/suppliers - Fetch paginated suppliers (admin only)
@app.get("/api/suppliers", response_model=dict)
async def get_suppliers(page: int = 1, limit: int = 10, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    suppliers_coll = db["suppliers"]
    products_coll = db["products"]
    
    skip = (page - 1) * limit
    total = suppliers_coll.count_documents({})
    suppliers = list(suppliers_coll.find().skip(skip).limit(limit))
    
    # Add product count for each supplier
    data = []
    for s in suppliers:
        product_count = products_coll.count_documents({"supplierId": str(s["_id"])})
        data.append({"id": str(s["_id"]), **s, "productCount": product_count})
    
    return {
        "data": data,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }

# POST /api/suppliers - Add a new supplier (admin only)
@app.post("/api/suppliers", response_model=dict)
async def create_supplier(supplier: Supplier, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    suppliers_coll = db["suppliers"]
    supplier_data = supplier.dict()
    result = suppliers_coll.insert_one(supplier_data)
    return {"data": {"id": str(result.inserted_id), **supplier_data}}

# PUT /api/suppliers/{id} - Update a supplier (admin only)
@app.put("/api/suppliers/{id}", response_model=dict)
async def update_supplier(id: str, supplier: Supplier, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    suppliers_coll = db["suppliers"]
    update_data = supplier.dict(exclude_unset=True)  # Only update provided fields
    result = suppliers_coll.update_one({"_id": ObjectId(id)}, {"$set": update_data})
    
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Supplier not found")
    
    updated_supplier = suppliers_coll.find_one({"_id": ObjectId(id)})
    product_count = db["products"].count_documents({"supplierId": id})
    return {"data": {"id": str(updated_supplier["_id"]), **updated_supplier, "productCount": product_count}}

# DELETE /api/suppliers/{id} - Delete a supplier (admin only)
@app.delete("/api/suppliers/{id}", response_model=dict)
async def delete_supplier(id: str, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
    
    suppliers_coll = db["suppliers"]
    products_coll = db["products"]
    
    # Check if supplier has products
    product_count = products_coll.count_documents({"supplierId": id})
    if product_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete supplier with associated products")
    
    result = suppliers_coll.delete_one({"_id": ObjectId(id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Supplier not found")
    
    return {"data": {"message": "Supplier deleted successfully"}}

# --- User Profile Endpoint ---
class UserUpdate(BaseModel):
    name: str
    email: EmailStr
    password: Optional[str] = None
    lowStockThreshold: int

@app.put("/api/user/profile", response_model=dict)
async def update_user_profile(update_data: UserUpdate, auth=Depends(with_auth), db=Depends(get_db)):
    user = auth
    users_coll = db["users"]
    
    update_dict = update_data.dict(exclude_unset=True)  # Only include provided fields
    if "password" in update_dict and update_dict["password"]:
        salt = bcrypt.gensalt()
        update_dict["password"] = bcrypt.hashpw(update_dict["password"].encode("utf-8"), salt).decode("utf-8")
    
    result = users_coll.update_one({"_id": ObjectId(user["userId"])}, {"$set": update_dict})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    
    updated_user = users_coll.find_one({"_id": ObjectId(user["userId"])})
    updated_user.pop("password", None)  # Remove password from response
    return {"data": {"id": str(updated_user["_id"]), **updated_user}}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)