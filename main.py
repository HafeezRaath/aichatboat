from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import requests
import json
import os
import base64
import uuid
from datetime import datetime, timedelta
import httpx

# Configuration
SHOPIFY_SHOP_DOMAIN = os.getenv("SHOPIFY_SHOP_DOMAIN", "your-store.myshopify.com")
SHOPIFY_ADMIN_API_TOKEN = os.getenv("SHOPIFY_ADMIN_API_TOKEN", "")
SHOPIFY_STOREFRONT_ACCESS_TOKEN = os.getenv("SHOPIFY_STOREFRONT_ACCESS_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

app = FastAPI(title="REZON AI VTON Engine", version="1.0.0")

# CORS - Allow Shopify domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== ROOT HANDLER ====================

@app.get("/")
async def root():
    return {"message": "REZON AI VTON Engine Running", "version": "1.0.0", "status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ==================== MODELS ====================

class ChatMessage(BaseModel):
    role: str
    content: str
    product_cards: Optional[List[Dict]] = None
    image_url: Optional[str] = None

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    session_id: str
    product_context: Optional[str] = None

class DiscountRequest(BaseModel):
    percentage: float = 5.0
    customer_email: Optional[str] = None
    product_id: Optional[str] = None

class VTONRequest(BaseModel):
    user_image_url: str
    product_image_url: str
    product_id: str
    session_id: str

class ProductFetchRequest(BaseModel):
    query: Optional[str] = None
    product_id: Optional[str] = None
    limit: int = 5

# ==================== SHOPIFY CLIENT ====================

class ShopifyClient:
    def __init__(self, shop_domain: str, admin_token: str, storefront_token: str):
        self.shop_domain = shop_domain
        self.admin_url = f"https://{shop_domain}/admin/api/2024-07/graphql.json"
        self.storefront_url = f"https://{shop_domain}/api/2024-07/graphql.json"
        self.admin_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": admin_token
        }
        self.storefront_headers = {
            "Content-Type": "application/json",
            "X-Shopify-Storefront-Access-Token": storefront_token
        }

    async def fetch_products(self, query: str = None, limit: int = 5) -> List[Dict]:
        search_query = f"title:*{query}*" if query else ""
        
        graphql_query = """
        query getProducts($query: String, $limit: Int!) {
            products(first: $limit, query: $query) {
                edges {
                    node {
                        id
                        title
                        description
                        handle
                        priceRange {
                            minVariantPrice {
                                amount
                                currencyCode
                            }
                        }
                        images(first: 1) {
                            edges {
                                node {
                                    url
                                    altText
                                }
                            }
                        }
                        variants(first: 1) {
                            edges {
                                node {
                                    id
                                    price {
                                        amount
                                        currencyCode
                                    }
                                    compareAtPrice {
                                        amount
                                        currencyCode
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        
        variables = {"query": search_query, "limit": limit}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.storefront_url,
                headers=self.storefront_headers,
                json={"query": graphql_query, "variables": variables}
            )
            data = response.json()
            
        if "errors" in data:
            raise HTTPException(status_code=400, detail=data["errors"])
            
        products = []
        for edge in data["data"]["products"]["edges"]:
            node = edge["node"]
            variant = node["variants"]["edges"][0]["node"] if node["variants"]["edges"] else None
            image = node["images"]["edges"][0]["node"] if node["images"]["edges"] else None
            
            products.append({
                "id": node["id"],
                "title": node["title"],
                "description": node["description"],
                "handle": node["handle"],
                "price": variant["price"]["amount"] if variant else "0.00",
                "compare_at_price": variant["compareAtPrice"]["amount"] if variant and variant["compareAtPrice"] else None,
                "currency": variant["price"]["currencyCode"] if variant else "PKR",
                "image_url": image["url"] if image else "",
                "variant_id": variant["id"] if variant else None
            })
        
        return products

    async def create_discount_code(self, percentage: float = 5.0, prefix: str = "AI") -> Dict:
        code = f"{prefix}{uuid.uuid4().hex[:6].upper()}"
        
        mutation = """
        mutation discountCodeBasicCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
            discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                    id
                    codeDiscount {
                        ... on DiscountCodeBasic {
                            title
                            codes(first: 1) {
                                edges {
                                    node {
                                        code
                                    }
                                }
                            }
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "basicCodeDiscount": {
                "title": f"AI Generated {percentage}% Off",
                "code": code,
                "startsAt": datetime.utcnow().isoformat() + "Z",
                "endsAt": (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z",
                "customerSelection": {"all": True},
                "customerGets": {
                    "value": {"percentage": percentage},
                    "items": {"all": True}
                },
                "usageLimit": 1
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.admin_url,
                headers=self.admin_headers,
                json={"query": mutation, "variables": variables}
            )
            data = response.json()
        
        if data.get("data", {}).get("discountCodeBasicCreate", {}).get("userErrors"):
            errors = data["data"]["discountCodeBasicCreate"]["userErrors"]
            raise HTTPException(status_code=400, detail=errors)
        
        discount_node = data["data"]["discountCodeBasicCreate"]["codeDiscountNode"]
        return {
            "code": code,
            "percentage": percentage,
            "discount_id": discount_node["id"],
            "expires_at": variables["basicCodeDiscount"]["endsAt"]
        }

    async def create_cart(self, variant_id: str, quantity: int = 1) -> Dict:
        mutation = """
        mutation cartCreate($input: CartInput!) {
            cartCreate(input: $input) {
                cart {
                    id
                    checkoutUrl
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """
        
        variables = {
            "input": {
                "lines": [{"quantity": quantity, "merchandiseId": variant_id}]
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.storefront_url,
                headers=self.storefront_headers,
                json={"query": mutation, "variables": variables}
            )
            return response.json()

shopify = ShopifyClient(SHOPIFY_SHOP_DOMAIN, SHOPIFY_ADMIN_API_TOKEN, SHOPIFY_STOREFRONT_ACCESS_TOKEN)

# ==================== AI SERVICE ====================

class AIService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.url = "https://api.openai.com/v1/chat/completions"
    
    async def chat_with_products(self, messages: List[Dict], products: List[Dict] = None) -> Dict:
        system_prompt = """You are REZON AI, a premium fashion assistant for a Shopify store. 
You help customers find products, provide styling advice, and can recommend items.
When recommending products, return them in a structured format.
Be conversational, friendly, and use Urdu/Hinglish mix if the customer uses it.
Always be concise but helpful."""

        formatted_messages = [{"role": "system", "content": system_prompt}]
        
        for msg in messages:
            content = msg.content
            if products and msg.role == "user":
                content += f"\\n\\nAvailable Products: {json.dumps(products)}"
            formatted_messages.append({"role": msg.role, "content": content})
        
        functions = [
            {
                "name": "show_product_cards",
                "description": "Show product cards to the user when they express interest in buying or viewing products",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of product IDs to show"
                        },
                        "message": {
                            "type": "string",
                            "description": "Friendly message to accompany the products"
                        }
                    },
                    "required": ["product_ids", "message"]
                }
            },
            {
                "name": "generate_discount",
                "description": "Generate a discount code when user is ready to purchase or asks for a deal",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "percentage": {
                            "type": "number",
                            "description": "Discount percentage (default 5)"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Why the discount is being offered"
                        }
                    },
                    "required": ["percentage"]
                }
            }
        ]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o",
                    "messages": formatted_messages,
                    "functions": functions,
                    "function_call": "auto",
                    "temperature": 0.7
                }
            )
            
        result = response.json()
        message = result["choices"][0]["message"]
        
        response_data = {
            "text": message.get("content", ""),
            "function_call": None,
            "product_cards": None
        }
        
        if message.get("function_call"):
            func_name = message["function_call"]["name"]
            func_args = json.loads(message["function_call"]["arguments"])
            response_data["function_call"] = {"name": func_name, "args": func_args}
            
        return response_data

ai_service = AIService(OPENAI_API_KEY)

# ==================== API ROUTES ====================

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        products = None
        if any(keyword in request.messages[-1].content.lower() for keyword in 
               ["product", "buy", "price", "dress", "shirt", "wallet", "kapra", "cheez"]):
            products = await shopify.fetch_products(limit=5)
        
        ai_response = await ai_service.chat_with_products(request.messages, products)
        
        if ai_response.get("function_call", {}).get("name") == "show_product_cards":
            product_ids = ai_response["function_call"]["args"]["product_ids"]
            product_cards = await shopify.fetch_products(limit=len(product_ids))
            ai_response["product_cards"] = product_cards
            ai_response["text"] = ai_response["function_call"]["args"]["message"]
        
        return JSONResponse(content={
            "success": True,
            "response": ai_response["text"],
            "product_cards": ai_response.get("product_cards"),
            "session_id": request.session_id
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/products")
async def get_products(request: ProductFetchRequest):
    try:
        products = await shopify.fetch_products(query=request.query, limit=request.limit)
        return {"success": True, "products": products}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/discount/generate")
async def generate_discount(request: DiscountRequest):
    try:
        discount = await shopify.create_discount_code(percentage=request.percentage, prefix="AI")
        return {
            "success": True,
            "discount": discount,
            "message": f"Aap ke liye {request.percentage}% discount code generate ho gaya hai!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/vton/process")
async def process_vton(request: VTONRequest):
    return {"success": True, "status": "processing", "message": "VTON processing started"}

@app.post("/api/cart/create")
async def create_cart(variant_id: str, quantity: int = 1):
    try:
        cart = await shopify.create_cart(variant_id, quantity)
        return {"success": True, "cart": cart}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        file_id = f"{uuid.uuid4()}_{file.filename}"
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, file_id)
        
        with open(file_path, "wb") as f:
            f.write(contents)
        
        return {
            "success": True,
            "url": f"/uploads/{file_id}",
            "file_id": file_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

print("- Added /health endpoint")
print("- Port reads from PORT env var (Railway compatible)")
