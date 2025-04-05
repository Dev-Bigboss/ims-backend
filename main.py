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
from pydantic import EmailStr

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")
JWT_SECRET = os.getenv("JWT_SECRET")

app = FastAPI()

from fastapi.staticfiles import StaticFiles
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


# --- Login Endpoint ---
@app.post("/api/login", response_model=dict)
async def login(login: LoginRequest):
    db = get_db()["users"]
    
    # Find user by email
    user = db.find_one({"email": login.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not bcrypt.checkpw(login.password.encode("utf-8"), user["password"].encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Generate JWT
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server configuration error")
    
    token = jwt.encode(
        {"userId": str(user["_id"]), "role": user["role"]},
        JWT_SECRET,
        algorithm="HS256"
    )
    
    return {"token": token}

# --- Register Endpoint ---
@app.post("/api/register", response_model=dict)
async def register(register: RegisterRequest):
    db = get_db()["users"]
    
    # Check for existing user
    if db.find_one({"email": register.email}):
        raise HTTPException(status_code=409, detail="User already exists")
    
    # Restrict admin role (force customer unless authorized)
    user_role = "customer" if register.role == "admin" else register.role
    
    # Hash password
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(register.password.encode("utf-8"), salt).decode("utf-8")
    
    # Create user
    user_data = {
        "name": register.name,
        "email": register.email,
        "password": hashed_password,
        "role": user_role,
        "lowStockThreshold": 10,
        "createdAt": datetime.utcnow()
    }
    result = db.insert_one(user_data)
    
    # Generate JWT
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server configuration error")
    
    token = jwt.encode(
        {"userId": str(result.inserted_id), "role": user_role},
        JWT_SECRET,
        algorithm="HS256"
    )
    
    return {"token": token}

# --- Activity Endpoints ---
@app.get("/api/activities", response_model=dict)
async def get_activities(request: Request, page: int = 1, limit: int = 10, auth=Depends(with_auth)):
    db = get_db()["activities"]
    skip = (page - 1) * limit
    activities = list(db.find().skip(skip).limit(limit).sort("createdAt", -1))
    total = db.count_documents({})
    activities = [Activity(**{**act, "_id": str(act["_id"])}) for act in activities]
    return {"activities": activities, "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.post("/api/activities", response_model=dict)
async def create_activity(activity: Activity, request: Request, auth=Depends(with_auth)):
    db = get_db()["activities"]
    result = db.insert_one(activity.dict(exclude={"id"}))
    return {"activity": {**activity.dict(), "_id": str(result.inserted_id)}}

# --- New Route: Features ---
@app.get("/api/features", response_model=List[dict])
async def get_features():
    # Static data (no DB needed yet—add MongoDB model if dynamic later)
    features = [
        {"icon": "FaShoppingCart", "title": "Seamless Shopping", "desc": "Browse, cart, and checkout in Naira—fast and intuitive."},
        {"icon": "FaCogs", "title": "Smart Admin Tools", "desc": "Manage stock, orders, and suppliers with ease."},
        {"icon": "FaChartLine", "title": "Real-Time Analytics", "desc": "Gain insights with live sales and stock data."},
    ]
    return features

# --- New Route: Feedback ---
@app.get("/api/feedback", response_model=dict)
async def get_feedback(request: Request, page: int = 1, limit: int = 10, productId: Optional[str] = None, auth=Depends(with_auth)):
    db = get_db()["feedback"]
    user = request.state.user
    skip = (page - 1) * limit

    if productId:
        feedback = list(db.find({"productId": productId}).sort("createdAt", -1))
        feedback = [Feedback(**{**f, "_id": str(f["_id"])}) for f in feedback]
        return {"feedback": feedback}

    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    feedback = list(db.find().skip(skip).limit(limit).sort("createdAt", -1))
    total = db.count_documents({})
    feedback = [Feedback(**{**f, "_id": str(f["_id"])}) for f in feedback]
    return {"feedback": feedback, "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.post("/api/feedback", response_model=dict)
async def create_feedback(feedback: Feedback, request: Request, auth=Depends(with_auth)):
    db = get_db()["feedback"]
    user = request.state.user
    feedback_data = feedback.dict(exclude={"id"})
    feedback_data["userId"] = user["userId"]
    result = db.insert_one(feedback_data)
    return {"feedback": {**feedback_data, "_id": str(result.inserted_id)}}

# --- New Route: Order History ---
@app.get("/api/order-history", response_model=dict)
async def get_order_history(request: Request, id: Optional[str] = None, page: int = 1, limit: int = 10, auth=Depends(with_auth)):
    db = get_db()["orders"]
    user = request.state.user
    skip = (page - 1) * limit

    if id:
        order = db.find_one({"_id": ObjectId(id), "customerId": user["userId"]})
        if not order:
            raise HTTPException(status_code=404, detail="Order not found or not authorized")
        return {"order": Order(**{**order, "_id": str(order["_id"])})}

    orders = list(db.find({"customerId": user["userId"]}).skip(skip).limit(limit).sort("orderDate", -1))
    total = db.count_documents({"customerId": user["userId"]})
    orders = [Order(**{**o, "_id": str(o["_id"])}) for o in orders]
    return {"orders": orders, "total": total, "page": page, "pages": (total + limit - 1) // limit}

# --- New Route: Orders ---
@app.get("/api/orders", response_model=dict)
async def get_orders(request: Request, page: int = 1, limit: int = 10, auth=Depends(with_auth)):
    db = get_db()["orders"]
    skip = (page - 1) * limit
    orders = list(db.find().skip(skip).limit(limit).sort("orderDate", -1))
    total = db.count_documents({})
    orders = [Order(**{**o, "_id": str(o["_id"])}) for o in orders]
    return {"orders": orders, "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.get("/api/user/favorites", response_model=dict)
async def get_user_favorites(request: Request, auth=Depends(with_auth)):
    db = get_db()["users"]
    user = request.state.user
    user_data = db.find_one({"_id": ObjectId(user["userId"])}, {"favorites": 1})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    return {"favorites": user_data.get("favorites", [])}

@app.put("/api/user/favorites", response_model=dict)
async def update_user_favorites(request: Request, favorites: List[str], auth=Depends(with_auth)):
    db = get_db()["users"]
    user = request.state.user
    updated_user = db.find_one_and_update(
        {"_id": ObjectId(user["userId"])},
        {"$set": {"favorites": favorites}},
        return_document=True
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"favorites": updated_user["favorites"]}

@app.get("/api/user/cart", response_model=dict)
async def get_user_cart(request: Request, auth=Depends(with_auth)):
    db = get_db()["users"]
    user = request.state.user
    user_data = db.find_one({"_id": ObjectId(user["userId"])}, {"cartItems": 1})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    cart_items = [
        {"productId": item["productId"], "quantity": item["quantity"], "price": item["price"]}
        for item in user_data.get("cartItems", [])
    ]
    return {"cartItems": cart_items}

@app.put("/api/user/cart", response_model=dict)
async def update_user_cart(request: Request, cartItems: List[CartItem], auth=Depends(with_auth)):
    db = get_db()["users"]
    user = request.state.user
    cart_data = [item.dict() for item in cartItems]
    updated_user = db.find_one_and_update(
        {"_id": ObjectId(user["userId"])},
        {"$set": {"cartItems": cart_data}},
        return_document=True
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"cartItems": updated_user["cartItems"]}

# Update /api/orders to clear cart after successful order
@app.post("/api/orders", response_model=dict)
async def create_order(request: Request, items: List[OrderItem], auth=Depends(with_auth)):
    db = get_db()
    user = request.state.user

    if not items:
        raise HTTPException(status_code=400, detail="Cart items are required")

    order_items = []
    for item in items:
        product = db["products"].find_one({"_id": ObjectId(item.productId)})
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.productId} not found")
        if product["quantity"] < item.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {product['name']}")
        order_items.append({"productId": str(product["_id"]), "quantity": item.quantity, "price": product["price"]})

    total_amount = sum(item["price"] * item["quantity"] for item in order_items)
    order_data = {"customerId": user["userId"], "items": order_items, "totalAmount": total_amount, "status": "processing", "orderDate": datetime.utcnow()}
    result = db["orders"].insert_one(order_data)
    order_id = str(result.inserted_id)

    for item in order_items:
        db["products"].update_one({"_id": ObjectId(item["productId"])}, {"$inc": {"quantity": -item["quantity"]}})

    # Clear user's cart after successful order
    db["users"].update_one({"_id": ObjectId(user["userId"])}, {"$set": {"cartItems": []}})

    activity_data = {"action": "Created", "entityType": "order", "entityId": order_id, "details": f"Order #{order_id[-6:]} placed", "userId": user["userId"], "createdAt": datetime.utcnow()}
    db["activities"].insert_one(activity_data)

    return {"order": {**order_data, "_id": order_id}}

@app.put("/api/orders", response_model=dict)
async def update_order(request: Request, id: str, status: Literal["processing", "shipped", "completed", "cancelled"], auth=Depends(with_auth)):
    db = get_db()
    user = request.state.user

    order = db["orders"].find_one_and_update(
        {"_id": ObjectId(id)}, {"$set": {"status": status, "updatedAt": datetime.utcnow()}}, return_document=True
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Log activity
    activity_data = {
        "action": "Updated",
        "entityType": "order",
        "entityId": id,
        "details": f"Order #{id[-6:]} status updated to {status}",
        "userId": user["userId"],
        "createdAt": datetime.utcnow()
    }
    db["activities"].insert_one(activity_data)

    return {"order": Order(**{**order, "_id": str(order["_id"])})}

# --- Payment Endpoints ---
@app.get("/api/payments", response_model=List[Payment])
async def get_payments():
    db = get_db()["payments"]
    payments = list(db.find())
    return [Payment(**{**p, "_id": str(p["_id"])}) for p in payments]

@app.post("/api/payments", response_model=Payment)
async def create_payment(payment: Payment):
    db = get_db()["payments"]
    result = db.insert_one(payment.dict(exclude={"id"}))
    return Payment(**{**payment.dict(), "_id": str(result.inserted_id)})

# --- New Routes: Products ---
@app.get("/api/products", response_model=dict)
async def get_products(request: Request, id: Optional[str] = None, page: int = 1, limit: int = 10, auth=Depends(with_auth)):
    db = get_db()["products"]
    skip = (page - 1) * limit

    if id:
        product = db.find_one({"_id": ObjectId(id)})
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"product": Product(**{**product, "_id": str(product["_id"])})}

    products = list(db.find().skip(skip).limit(limit))
    total = db.count_documents({})
    products = [Product(**{**p, "_id": str(p["_id"])}) for p in products]
    return {"products": products, "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.post("/api/products", response_model=dict)
async def create_product(product: Product, request: Request, auth=Depends(with_auth)):
    db = get_db()["products"]
    user = request.state.user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    product_data = product.dict(exclude={"id"})
    result = db.insert_one(product_data)
    return {"product": {**product_data, "_id": str(result.inserted_id)}}

@app.put("/api/products", response_model=dict)
async def update_product(request: Request, id: str, product: Product, auth=Depends(with_auth)):
    db = get_db()["products"]
    updated_product = db.find_one_and_update(
        {"_id": ObjectId(id)}, {"$set": product.dict(exclude={"id"})}, return_document=True
    )
    if not updated_product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": Product(**{**updated_product, "_id": str(updated_product["_id"])})}

# --- New Route: Report ---
@app.get("/api/report", response_model=dict)
async def get_report(request: Request, auth=Depends(with_auth)):
    db = get_db()
    user = request.state.user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    products = list(db["products"].find())
    thirty_days_ago = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = thirty_days_ago.replace(day=thirty_days_ago.day - 30)
    orders = list(db["orders"].find({"orderDate": {"$gte": thirty_days_ago}}))
    suppliers = list(db["suppliers"].find())

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
    top_products_data = []
    for pid, count in top_products:
        product = db["products"].find_one({"_id": ObjectId(pid)})
        top_products_data.append({"name": product["name"] if product else "Unknown", "count": count})

    supplier_product_count = [{"supplierName": s["name"], "productCount": db["products"].count_documents({"supplierId": str(s["_id"])})} for s in suppliers]
    supplier_order_volume = []
    for s in suppliers:
        supplier_products = list(db["products"].find({"supplierId": str(s["_id"])}))
        supplier_product_ids = [str(p["_id"]) for p in supplier_products]
        order_count = sum(1 for o in orders if any(item["productId"] in supplier_product_ids for item in o["items"]))
        supplier_order_volume.append({"supplierName": s["name"], "orderCount": order_count})

    return {
        "products": [Product(**{**p, "_id": str(p["_id"])}) for p in products],
        "orders": [Order(**{**o, "_id": str(o["_id"])}) for o in orders],
        "stockLevels": {"inStock": in_stock, "lowStock": low_stock, "outOfStock": out_of_stock},
        "revenueByDay": revenue_by_day,
        "topProducts": top_products_data,
        "supplierProductCount": supplier_product_count,
        "supplierOrderVolume": supplier_order_volume,
    }

# --- New Routes: Suppliers ---
@app.get("/api/suppliers", response_model=dict)
async def get_suppliers(request: Request, page: int = 1, limit: int = 10, auth=Depends(with_auth)):
    db = get_db()["suppliers"]
    user = request.state.user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    skip = (page - 1) * limit
    suppliers = list(db.find().skip(skip).limit(limit))
    total = db.count_documents({})
    for s in suppliers:
        s["productCount"] = db["products"].count_documents({"supplierId": str(s["_id"])})
    suppliers = [Supplier(**{**s, "_id": str(s["_id"])}) for s in suppliers]
    return {"suppliers": suppliers, "total": total, "page": page, "pages": (total + limit - 1) // limit}

@app.post("/api/suppliers", response_model=dict)
async def create_supplier(supplier: Supplier, request: Request, auth=Depends(with_auth)):
    db = get_db()["suppliers"]
    user = request.state.user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    supplier_data = supplier.dict(exclude={"id"})
    result = db.insert_one(supplier_data)
    return {"supplier": {**supplier_data, "_id": str(result.inserted_id)}}

@app.put("/api/suppliers", response_model=dict)
async def update_supplier(request: Request, id: str, supplier: Supplier, auth=Depends(with_auth)):
    db = get_db()["suppliers"]
    user = request.state.user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    updated_supplier = db.find_one_and_update(
        {"_id": ObjectId(id)}, {"$set": supplier.dict(exclude={"id"})}, return_document=True
    )
    if not updated_supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"supplier": Supplier(**{**updated_supplier, "_id": str(updated_supplier["_id"])})}

@app.delete("/api/suppliers", response_model=dict)
async def delete_supplier(request: Request, id: str, auth=Depends(with_auth)):
    db = get_db()["suppliers"]
    user = request.state.user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    result = db.find_one_and_delete({"_id": ObjectId(id)})
    if not result:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {"message": "Supplier deleted"}

# --- New Route: Upload ---
@app.post("/api/upload", response_model=dict)
async def upload_image(request: Request, file: UploadFile = File(...), auth=Depends(with_auth)):
    db = get_db()
    user = request.state.user
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required")

    upload_dir = "public/uploads"
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = file.filename.split(".")[-1].lower()
    allowed_exts = {"jpeg", "jpg", "png", "webp", "gif", "svg"}
    if file_ext not in allowed_exts:
        raise HTTPException(status_code=400, detail="Only images are allowed (jpeg, jpg, png, webp, gif, svg)")

    file_name = f"{datetime.utcnow().timestamp()}-{os.urandom(4).hex()}.{file_ext}"
    file_path = os.path.join(upload_dir, file_name)

    async with aiofiles.open(file_path, "wb") as out_file:
        content = await file.read()
        await out_file.write(content)

    image_url = f"/uploads/{file_name}"
    return {"imageUrl": image_url}

# --- New Routes: User Profile ---
@app.get("/api/user/profile", response_model=dict)
async def get_user_profile(request: Request, auth=Depends(with_auth)):
    db = get_db()["users"]
    user = request.state.user
    user_data = db.find_one({"_id": ObjectId(user["userId"])})
    if not user_data:
        raise HTTPException(status_code=404, detail="User not found")
    user_data.pop("password", None)  # Exclude password
    return {"user": User(**{**user_data, "_id": str(user_data["_id"])})}

@app.put("/api/user/profile", response_model=dict)
async def update_user_profile(request: Request, name: Optional[str] = None, email: Optional[EmailStr] = None, password: Optional[str] = None, lowStockThreshold: Optional[int] = None, auth=Depends(with_auth)):
    db = get_db()["users"]
    user = request.state.user

    update_data = {}
    if name:
        update_data["name"] = name
    if email:
        update_data["email"] = email
    if password:
        salt = bcrypt.gensalt()
        update_data["password"] = bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
    if lowStockThreshold is not None:
        if lowStockThreshold < 0:
            raise HTTPException(status_code=400, detail="Low stock threshold must be a non-negative number")
        update_data["lowStockThreshold"] = lowStockThreshold

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields provided to update")

    updated_user = db.find_one_and_update(
        {"_id": ObjectId(user["userId"])}, {"$set": update_data}, return_document=True
    )
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    updated_user.pop("password", None)
    token = None
    if email or password:
        token = jwt.encode({"userId": str(updated_user["_id"]), "role": updated_user["role"]}, JWT_SECRET, algorithm="HS256")
    return {"user": User(**{**updated_user, "_id": str(updated_user["_id"])}), "token": token}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)